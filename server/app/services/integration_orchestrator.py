import json
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.mappers import (
    dumps_json,
    is_meaningful_outcome,
    is_terminal_or_milestone,
    map_outcome_to_writeback_payload,
    map_packet_to_launch_request,
    normalize_job_status,
    outcome_fingerprint,
)
from app.integrations.phios_client import IntegrationClientError, PhiOSClient
from app.integrations.schemas import (
    AgentExecutionOutcome,
    ContextPackRequest,
    LaunchMissionRequest,
    MissionContextPacket,
    OrchestrationRunRecord,
    PrepareMissionRequest,
    SoftwareTaskRequest,
)
from app.models import AlertEvent, IntegrationRun, WatcherEvent

ACTIVE_STATUSES = {'preparing_launch', 'launched', 'running', 'queued'}
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled', 'error'}
IMPORTANT_EVENT_TYPES = {'launched', 'terminal-state-reached', 'writeback-succeeded', 'writeback-failed', 'watched', 'unwatched'}


class IntegrationOrchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.phios = PhiOSClient()
        self.agentception = AgentCeptionClient()

    def _to_record(self, row: IntegrationRun) -> OrchestrationRunRecord:
        return OrchestrationRunRecord.model_validate(row.model_dump())

    def _parse_json(self, raw: str, default):
        try:
            return json.loads(raw or '')
        except Exception:
            return default

    def _parse_json_list(self, raw: str) -> list:
        value = self._parse_json(raw, [])
        return value if isinstance(value, list) else []

    def _log_event(self, event_type: str, *, run_id: int | None = None, status: str = '', latency_ms: float = 0.0, detail: dict | None = None):
        evt = WatcherEvent(run_id=run_id, event_type=event_type, status=status, latency_ms=latency_ms, detail_json=dumps_json(detail or {}))
        self.session.add(evt)
        self.session.commit()

    def _log_alert(self, run_id: int | None, alert_type: str, severity: str, detail: dict, delivery_status: str = 'logged'):
        evt = AlertEvent(run_id=run_id, alert_type=alert_type, severity=severity, delivery_status=delivery_status, detail_json=dumps_json(detail))
        self.session.add(evt)
        self.session.commit()

    def _maybe_send_alert(self, row: IntegrationRun, alert_type: str, severity: str, detail: dict):
        if not settings.agentora_missions_alerts_enabled:
            return
        if alert_type == 'terminal' and not settings.agentora_missions_alerts_on_terminal:
            return
        if alert_type == 'writeback_failed' and not settings.agentora_missions_alerts_on_writeback_failure:
            return
        if alert_type == 'high_risk' and not settings.agentora_missions_alerts_on_high_risk:
            return
        if not settings.agentora_missions_alerts_webhook_url:
            self._log_alert(row.id, alert_type, severity, detail, delivery_status='logged_only')
            return
        try:
            payload = {
                'alert_type': alert_type,
                'severity': severity,
                'run_id': row.id,
                'mission_title': row.mission_title,
                'repo': row.repo,
                'status': row.status,
                'writeback_status': row.writeback_status,
                'detail': detail,
                'at': datetime.utcnow().isoformat(),
            }
            httpx.post(settings.agentora_missions_alerts_webhook_url, json=payload, timeout=5)
            self._log_alert(row.id, alert_type, severity, detail, delivery_status='sent')
        except Exception as exc:
            self._log_alert(row.id, alert_type, severity, {'error': str(exc), **detail}, delivery_status='failed')

    def _build_snapshot(self, row: IntegrationRun) -> dict:
        return {
            'run_id': row.id,
            'prepared_packet': self._parse_json(row.phios_packet_json, {}),
            'launch_payload': self._parse_json(row.raw_payload_json, {}).get('launch_request', {}),
            'latest_outcome': self._parse_json(row.agentception_result_json, {}),
            'writeback': {
                'status': row.writeback_status,
                'at': row.writeback_at.isoformat() if row.writeback_at else None,
                'error': row.writeback_error,
            },
            'timeline_summary': self.run_timeline(row.id or 0) if row.id else [],
            'evaluation': {
                'mission_score': row.mission_score,
                'confidence_level': row.confidence_level,
                'completion_signal': row.completion_signal,
                'result_quality_signal': row.result_quality_signal,
                'writeback_readiness_signal': row.writeback_readiness_signal,
                'risk_signal': row.risk_signal,
            },
            'generated_at': datetime.utcnow().isoformat(),
            'schema_version': 'phase-f-v1',
        }

    def _evaluate_run(self, row: IntegrationRun, outcome: AgentExecutionOutcome | None = None) -> None:
        score = 0
        if row.status == 'completed':
            score += settings.agentora_missions_score_terminal_success_bonus
        elif row.status in {'failed', 'error', 'cancelled'}:
            score -= settings.agentora_missions_score_failure_penalty
        if row.pr_url:
            score += settings.agentora_missions_score_pr_bonus
        if self._parse_json_list(row.issue_urls_json):
            score += 10
        if self._parse_json_list(row.artifact_urls_json):
            score += 10
        if len((row.summary or '').strip()) >= settings.agentora_missions_score_summary_min_length:
            score += 15
        if row.writeback_status == 'written':
            score += settings.agentora_missions_score_writeback_success_bonus
        if row.writeback_status == 'failed':
            score -= settings.agentora_missions_score_failure_penalty // 2
        score = max(0, min(100, score))
        row.mission_score = score

        high_threshold = settings.agentora_missions_confidence_threshold_high
        med_threshold = settings.agentora_missions_confidence_threshold_medium
        row.confidence_level = 'high' if score >= high_threshold else ('medium' if score >= med_threshold else 'low')

        row.completion_signal = 'terminal' if row.status in TERMINAL_STATUSES else 'in_progress'
        row.result_quality_signal = 'high' if len((row.summary or '').strip()) >= 120 else ('medium' if len((row.summary or '').strip()) >= 40 else 'low')
        readiness = is_meaningful_outcome(outcome) if outcome else bool(row.summary)
        row.writeback_readiness_signal = 'high' if readiness else 'low'

        risk_points = 0
        if row.status in {'failed', 'error'}:
            risk_points += 2
        if row.writeback_status == 'failed':
            risk_points += 1
        if row.refresh_count >= 8 and row.status not in TERMINAL_STATUSES:
            risk_points += 1
        if row.confidence_level == 'low':
            risk_points += 1
        row.risk_signal = 'high' if risk_points >= settings.agentora_missions_risk_threshold_high else ('medium' if risk_points > 0 else 'low')

    def _persist_snapshot(self, row: IntegrationRun):
        row.mission_snapshot_json = dumps_json(self._build_snapshot(row))

    def prepare_mission_context(self, payload: PrepareMissionRequest) -> MissionContextPacket:
        packet = self.phios.get_context_pack(
            ContextPackRequest(
                persona_id=payload.persona_id,
                task='software_mission',
                repo=payload.repo,
                objective=payload.objective,
                operator_intent=payload.operator_intent,
                mission_title=payload.mission_title,
                limit=8,
            )
        )
        self._log_event('prepared', status='ok', detail={'repo': payload.repo, 'persona_id': payload.persona_id})
        return packet

    def launch_software_mission(self, payload: LaunchMissionRequest) -> OrchestrationRunRecord:
        packet = payload.prepared_packet or self.prepare_mission_context(
            PrepareMissionRequest(
                persona_id=payload.persona_id,
                repo=payload.repo,
                mission_title=payload.mission_title,
                objective=payload.objective,
                operator_intent=payload.operator_intent,
                constraints=payload.constraints,
            )
        )
        launch_request = map_packet_to_launch_request(packet, payload.acceptance_criteria, payload.constraints, payload.dry_run)

        row = IntegrationRun(
            status='preparing_launch',
            persona_id=payload.persona_id,
            repo=payload.repo,
            mission_title=payload.mission_title,
            objective=payload.objective,
            operator_intent=payload.operator_intent,
            context_summary=packet.summary,
            dispatch_brief=dumps_json(packet.dispatch_brief.model_dump(mode='json')),
            acceptance_criteria_json=dumps_json(payload.acceptance_criteria),
            constraints_json=dumps_json(payload.constraints),
            success_criteria_json=dumps_json([x.model_dump(mode='json') for x in packet.success_criteria]),
            recommended_actions_json=dumps_json(packet.recommended_next_actions),
            phios_session_id=packet.session_id,
            phios_packet_json=dumps_json(packet.model_dump(mode='json')),
            raw_payload_json=dumps_json({'launch_request': launch_request.model_dump(mode='json')}),
            auto_writeback_enabled=settings.agentora_missions_auto_writeback,
            writeback_policy='auto' if settings.agentora_missions_auto_writeback else 'manual',
            watch_enabled=True,
        )
        self._evaluate_run(row)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)

        try:
            launch = self.agentception.launch_job(launch_request)
            row.status = 'launched'
            row.updated_at = datetime.utcnow()
            row.last_refreshed_at = datetime.utcnow()
            row.agentception_job_id = launch.job_id
            row.agentception_status = launch.status
            row.summary = launch.message
            row.raw_payload_json = dumps_json({'phios_packet': packet.model_dump(mode='json'), 'launch_request': launch_request.model_dump(mode='json'), 'launch_response': launch.model_dump(mode='json')})
            self._evaluate_run(row)
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()
            self._log_event('launched', run_id=row.id, status=launch.status)
            self.session.refresh(row)
            return self._to_record(row)
        except Exception as exc:
            row.status = 'error'
            row.updated_at = datetime.utcnow()
            row.error_message = str(exc)
            self._evaluate_run(row)
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()
            self._log_event('launched', run_id=row.id, status='error', detail={'error': str(exc)})
            self.session.refresh(row)
            return self._to_record(row)

    def run_software_task_with_context(self, persona_id: str, repo: str, objective: str, acceptance_criteria: list[str], constraints: list[str], dry_run: bool) -> OrchestrationRunRecord:
        return self.launch_software_mission(LaunchMissionRequest(persona_id=persona_id, repo=repo, mission_title=objective[:80], objective=objective, acceptance_criteria=acceptance_criteria, constraints=constraints, dry_run=dry_run))

    def launch_from_request(self, payload: SoftwareTaskRequest) -> OrchestrationRunRecord:
        return self.launch_software_mission(LaunchMissionRequest(**payload.model_dump(mode='json')))

    def list_runs(self, *, status: str | None = None, repo: str | None = None, persona_id: str | None = None, writeback_status: str | None = None, confidence_level: str | None = None, mission_score_min: int | None = None, mission_score_max: int | None = None, start_date: datetime | None = None, end_date: datetime | None = None, search: str | None = None, limit: int = 50, offset: int = 0, watch_enabled_only: bool = False) -> list[OrchestrationRunRecord]:
        q = select(IntegrationRun)
        if status:
            q = q.where(IntegrationRun.status == status)
        if repo:
            q = q.where(IntegrationRun.repo.contains(repo))
        if persona_id:
            q = q.where(IntegrationRun.persona_id.contains(persona_id))
        if writeback_status:
            q = q.where(IntegrationRun.writeback_status == writeback_status)
        if confidence_level:
            q = q.where(IntegrationRun.confidence_level == confidence_level)
        if mission_score_min is not None:
            q = q.where(IntegrationRun.mission_score >= mission_score_min)
        if mission_score_max is not None:
            q = q.where(IntegrationRun.mission_score <= mission_score_max)
        if start_date:
            q = q.where(IntegrationRun.created_at >= start_date)
        if end_date:
            q = q.where(IntegrationRun.created_at <= end_date)
        if search:
            q = q.where(IntegrationRun.mission_title.contains(search) | IntegrationRun.objective.contains(search) | IntegrationRun.summary.contains(search))
        if watch_enabled_only:
            q = q.where(IntegrationRun.watch_enabled == True)  # noqa: E712
        rows = self.session.exec(q.order_by(IntegrationRun.created_at.desc()).offset(offset).limit(limit)).all()
        return [self._to_record(r) for r in rows]

    def list_active_runs_for_watcher(self, limit: int) -> list[IntegrationRun]:
        q = select(IntegrationRun).where(IntegrationRun.watch_enabled == True)  # noqa: E712
        q = q.where(IntegrationRun.status.in_(ACTIVE_STATUSES))
        return self.session.exec(q.order_by(IntegrationRun.updated_at.desc()).limit(limit)).all()

    def get_run(self, run_id: int) -> OrchestrationRunRecord | None:
        row = self.session.get(IntegrationRun, run_id)
        return self._to_record(row) if row else None

    def set_watch(self, run_id: int, enabled: bool) -> OrchestrationRunRecord:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        row.watch_enabled = enabled
        row.updated_at = datetime.utcnow()
        self.session.add(row)
        self.session.commit()
        self._log_event('watched' if enabled else 'unwatched', run_id=run_id, status='ok')
        self.session.refresh(row)
        return self._to_record(row)

    def refresh_run(self, run_id: int, *, source: str = 'manual') -> OrchestrationRunRecord:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.agentception_job_id:
            raise IntegrationClientError('Run has no AgentCeption job id yet')

        t0 = datetime.utcnow()
        self._log_event('refresh_attempt', run_id=run_id, status=source)
        try:
            status = self.agentception.get_job_status(row.agentception_job_id)
            outcome: AgentExecutionOutcome = normalize_job_status(status)
            outcome_hash = outcome_fingerprint(outcome)
            row.updated_at = datetime.utcnow()
            row.last_refreshed_at = datetime.utcnow()
            row.watch_error = ''
            row.refresh_count = (row.refresh_count or 0) + 1
            row.status = 'running' if outcome.status not in TERMINAL_STATUSES else outcome.status
            row.agentception_status = outcome.status
            row.branch = outcome.branch or row.branch
            row.pr_url = outcome.pr_url or row.pr_url
            if outcome.issue_urls:
                row.issue_urls_json = dumps_json(outcome.issue_urls)
            if outcome.artifact_urls:
                row.artifact_urls_json = dumps_json(outcome.artifact_urls)
            row.summary = outcome.summary or row.summary
            row.agentception_result_json = dumps_json(outcome.model_dump(mode='json'))
            row.last_outcome_hash = outcome_hash
            if row.status in TERMINAL_STATUSES:
                row.watch_enabled = False
                self._log_event('terminal-state-reached', run_id=run_id, status=row.status)
                self._maybe_send_alert(row, 'terminal', 'info', {'status': row.status})
            self._evaluate_run(row, outcome)
            if row.risk_signal == 'high':
                self._maybe_send_alert(row, 'high_risk', 'high', {'mission_score': row.mission_score, 'status': row.status})
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()

            if source == 'watcher' and row.auto_writeback_enabled:
                self._maybe_auto_writeback(row, outcome, outcome_hash)

            latency_ms = (datetime.utcnow() - t0).total_seconds() * 1000
            self._log_event('watcher-refreshed' if source == 'watcher' else 'refreshed', run_id=run_id, status=row.status, latency_ms=latency_ms)
            self.session.refresh(row)
            return self._to_record(row)
        except Exception as exc:
            row.watch_error = str(exc)
            self.session.add(row)
            self.session.commit()
            latency_ms = (datetime.utcnow() - t0).total_seconds() * 1000
            self._log_event('refresh-failed', run_id=run_id, status='error', latency_ms=latency_ms, detail={'error': str(exc)})
            raise

    def _maybe_auto_writeback(self, row: IntegrationRun, outcome: AgentExecutionOutcome, outcome_hash: str) -> None:
        if not settings.agentora_missions_auto_writeback:
            return
        if row.writeback_policy not in {'auto', 'manual_or_auto'}:
            return
        if not is_terminal_or_milestone(outcome) or not is_meaningful_outcome(outcome):
            return
        now = datetime.utcnow()
        if row.last_writeback_attempt_at and now - row.last_writeback_attempt_at < timedelta(seconds=settings.agentora_missions_writeback_debounce_seconds):
            self._log_event('writeback-skipped-debounce', run_id=row.id, status=row.status)
            return
        if row.writeback_status == 'written' and row.last_writeback_hash == outcome_hash:
            self._log_event('writeback-skipped-duplicate-hash', run_id=row.id, status=row.status)
            return
        try:
            self._perform_writeback(row, outcome, operator_notes='auto-writeback from watcher', tags=['phase-f', 'auto'])
        except Exception:
            pass

    def _perform_writeback(self, row: IntegrationRun, outcome: AgentExecutionOutcome, operator_notes: str, tags: list[str] | None) -> dict:
        payload = map_outcome_to_writeback_payload(session_id=row.phios_session_id, task_id=row.agentception_job_id or f'run-{row.id}', repo=row.repo, objective=row.objective, outcome=outcome, tags=tags, operator_notes=operator_notes)
        row.last_writeback_attempt_at = datetime.utcnow()
        self.session.add(row)
        self.session.commit()
        self._log_event('writeback-attempted', run_id=row.id, status=row.status)
        try:
            result = self.phios.write_mission_result(payload)
            row.writeback_status = 'written'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = ''
            row.last_writeback_hash = outcome_fingerprint(outcome)
            self._evaluate_run(row, outcome)
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()
            self._log_event('writeback-succeeded', run_id=row.id, status=row.status)
            return {'ok': True, 'result': result}
        except Exception as exc:
            row.writeback_status = 'failed'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = str(exc)
            self._evaluate_run(row, outcome)
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()
            self._log_event('writeback-failed', run_id=row.id, status=row.status, detail={'error': str(exc)})
            self._maybe_send_alert(row, 'writeback_failed', 'high', {'error': str(exc)})
            raise

    def writeback_run(self, run_id: int, operator_notes: str = '', tags: list[str] | None = None) -> dict:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.phios_session_id:
            raise IntegrationClientError('Run has no PhiOS session id yet')
        if row.agentception_result_json:
            outcome = AgentExecutionOutcome.model_validate_json(row.agentception_result_json)
        else:
            outcome = AgentExecutionOutcome(job_id=row.agentception_job_id or f'run-{row.id}', status=row.agentception_status or row.status, phase='', branch=row.branch, pr_url=row.pr_url, issue_urls=[], artifact_urls=[], summary=row.summary)
        return self._perform_writeback(row, outcome, operator_notes=operator_notes, tags=tags)

    def list_watcher_events(self, limit: int = 100) -> list[dict]:
        rows = self.session.exec(select(WatcherEvent).order_by(WatcherEvent.created_at.desc()).limit(limit)).all()
        return [r.model_dump() for r in rows]

    def list_alert_events(self, limit: int = 50) -> list[dict]:
        rows = self.session.exec(select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(limit)).all()
        return [r.model_dump() for r in rows]

    def get_metrics(self) -> dict:
        rows = self.session.exec(select(WatcherEvent)).all()
        latency = [r.latency_ms for r in rows if r.latency_ms > 0]
        def count(ev: str):
            return sum(1 for r in rows if r.event_type == ev)
        watched = len(self.list_active_runs_for_watcher(settings.agentora_missions_watcher_max_active_runs))
        return {
            'refresh_attempts': count('refresh_attempt'),
            'refresh_successes': count('refreshed') + count('watcher-refreshed'),
            'refresh_failures': count('refresh-failed'),
            'average_refresh_latency_ms': (sum(latency) / len(latency)) if latency else 0.0,
            'last_refresh_latency_ms': latency[-1] if latency else 0.0,
            'skipped_writebacks_debounce': count('writeback-skipped-debounce'),
            'skipped_writebacks_duplicate_hash': count('writeback-skipped-duplicate-hash'),
            'successful_writebacks': count('writeback-succeeded'),
            'failed_writebacks': count('writeback-failed'),
            'runs_currently_watched': watched,
            'terminal_runs_completed_by_watcher': count('terminal-state-reached'),
        }

    def get_insights(self) -> dict:
        runs = self.session.exec(select(IntegrationRun)).all()
        by_status, by_persona, by_repo, risk_counts = {}, {}, {}, {}
        for r in runs:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_persona[r.persona_id] = by_persona.get(r.persona_id, 0) + 1
            by_repo[r.repo] = by_repo.get(r.repo, 0) + 1
            risk_counts[r.risk_signal] = risk_counts.get(r.risk_signal, 0) + 1
        total = len(runs) or 1
        writeback_written = sum(1 for r in runs if r.writeback_status == 'written')
        terminal_success = sum(1 for r in runs if r.status == 'completed')
        terminal_total = sum(1 for r in runs if r.status in TERMINAL_STATUSES) or 1
        avg_score = sum(r.mission_score for r in runs) / total
        avg_refresh_by_status = {s: (sum(r.refresh_count for r in runs if r.status == s) / c) for s, c in by_status.items()}
        top_repos = sorted(by_repo.items(), key=lambda x: x[1], reverse=True)[:5]
        pr_presence = sum(1 for r in runs if r.pr_url) / total
        return {
            'missions_by_status': by_status,
            'missions_by_persona': by_persona,
            'writeback_success_rate': writeback_written / total,
            'average_watcher_refresh_count_by_status': avg_refresh_by_status,
            'top_repos_by_mission_count': top_repos,
            'terminal_success_rate': terminal_success / terminal_total,
            'average_mission_score': avg_score,
            'top_risk_signals': sorted(risk_counts.items(), key=lambda x: x[1], reverse=True),
            'average_pr_presence_rate': pr_presence,
        }

    def run_timeline(self, run_id: int) -> list[dict]:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        events = [{'event': 'prepared', 'at': row.created_at.isoformat(), 'status': 'ok'}, {'event': 'launched', 'at': row.updated_at.isoformat(), 'status': row.agentception_status, 'job_id': row.agentception_job_id}]
        watcher_events = self.session.exec(select(WatcherEvent).where(WatcherEvent.run_id == run_id).order_by(WatcherEvent.created_at.asc())).all()
        for e in watcher_events:
            events.append({'event': e.event_type, 'at': e.created_at.isoformat(), 'status': e.status, 'latency_ms': e.latency_ms})
        return events

    def compare_runs(self, left_run_id: int, right_run_id: int) -> dict:
        left = self.session.get(IntegrationRun, left_run_id)
        right = self.session.get(IntegrationRun, right_run_id)
        if not left or not right:
            raise IntegrationClientError('Both runs must exist for compare')

        def phase_of(r: IntegrationRun) -> str:
            return self._parse_json(r.agentception_result_json, {}).get('phase', '')

        def packet_list(r: IntegrationRun, key: str) -> list[str]:
            value = self._parse_json(r.phios_packet_json, {}).get(key, [])
            if not isinstance(value, list):
                return []
            out = []
            for item in value:
                out.append(item.get('name') if isinstance(item, dict) else str(item))
            return out

        fields = {
            'mission_title': (left.mission_title, right.mission_title),
            'persona_id': (left.persona_id, right.persona_id),
            'repo': (left.repo, right.repo),
            'objective': (left.objective, right.objective),
            'status': (left.status, right.status),
            'phase': (phase_of(left), phase_of(right)),
            'branch': (left.branch, right.branch),
            'pr_url': (left.pr_url, right.pr_url),
            'writeback_status': (left.writeback_status, right.writeback_status),
        }
        diffs, severity = {}, {}

        def _sev(field: str, l, r):
            if l == r:
                return 'none'
            if field == 'status' and ({l, r} & {'failed', 'error'}) and ({l, r} & {'completed'}):
                return 'critical'
            if field == 'pr_url' and (not r and l):
                return 'high'
            if field == 'writeback_status' and {'written', 'failed'} == {l, r}:
                return 'high'
            if field == 'mission_score':
                try:
                    if abs(int(l) - int(r)) >= 25:
                        return 'high'
                except Exception:
                    pass
            if field in {'status', 'phase', 'branch'}:
                return 'medium'
            return 'low'

        for k, (lval, rval) in fields.items():
            if lval != rval:
                diffs[k] = {'left': lval, 'right': rval}
                severity[k] = _sev(k, lval, rval)

        score_sev = _sev('mission_score', left.mission_score, right.mission_score)
        if score_sev != 'none':
            diffs['mission_score'] = {'left': left.mission_score, 'right': right.mission_score}
            severity['mission_score'] = score_sev

        levels = ['none', 'low', 'medium', 'high', 'critical']
        overall = 'none'
        for s in severity.values():
            if levels.index(s) > levels.index(overall):
                overall = s

        left_followups = self._parse_json_list(left.recommended_actions_json)
        right_followups = self._parse_json_list(right.recommended_actions_json)
        left_success = self._parse_json_list(left.success_criteria_json)
        right_success = self._parse_json_list(right.success_criteria_json)
        left_risks = packet_list(left, 'risk_flags')
        right_risks = packet_list(right, 'risk_flags')
        left_timeline = self.run_timeline(left_run_id)
        right_timeline = self.run_timeline(right_run_id)

        interpretation = f'Overall compare severity is {overall}. Focus on status/writeback/PR deltas first.'

        return {
            'left': {'id': left.id, 'mission_title': left.mission_title, 'repo': left.repo, 'status': left.status, 'pr_url': left.pr_url, 'summary': left.summary, 'recommended_followups': left_followups, 'writeback_status': left.writeback_status},
            'right': {'id': right.id, 'mission_title': right.mission_title, 'repo': right.repo, 'status': right.status, 'pr_url': right.pr_url, 'summary': right.summary, 'recommended_followups': right_followups, 'writeback_status': right.writeback_status},
            'field_differences': diffs,
            'field_severity': severity,
            'overall_severity': overall,
            'summary_similarity_note': 'same' if (left.summary or '').strip() == (right.summary or '').strip() else 'different',
            'recommended_followups_delta': {'only_left': [x for x in left_followups if x not in right_followups], 'only_right': [x for x in right_followups if x not in left_followups]},
            'success_criteria_delta': {'only_left': [x for x in left_success if x not in right_success], 'only_right': [x for x in right_success if x not in left_success]},
            'risk_flags_delta': {'only_left': [x for x in left_risks if x not in right_risks], 'only_right': [x for x in right_risks if x not in left_risks]},
            'outcome_hash_equal': left.last_outcome_hash == right.last_outcome_hash,
            'timeline_length_comparison': {'left': len(left_timeline), 'right': len(right_timeline)},
            'interpretation': interpretation,
        }

    def get_snapshot(self, run_id: int) -> dict:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.mission_snapshot_json:
            self._persist_snapshot(row)
            self.session.add(row)
            self.session.commit()
        return self._parse_json(row.mission_snapshot_json, {})

    def get_retention_status(self) -> dict:
        now = datetime.utcnow()
        cutoff = now - timedelta(days=settings.agentora_missions_events_ttl_days)
        all_events = self.session.exec(select(WatcherEvent)).all()
        stale = [e for e in all_events if e.created_at < cutoff]
        by_run = {}
        for e in all_events:
            by_run[e.run_id] = by_run.get(e.run_id, 0) + 1
        over_limit_runs = {k: v for k, v in by_run.items() if k and v > settings.agentora_missions_events_max_per_run}
        return {
            'ttl_days': settings.agentora_missions_events_ttl_days,
            'max_per_run': settings.agentora_missions_events_max_per_run,
            'total_events': len(all_events),
            'stale_events': len(stale),
            'runs_over_limit': over_limit_runs,
            'compaction_enabled': settings.agentora_missions_compaction_enabled,
        }

    def compact_events(self) -> dict:
        now = datetime.utcnow()
        cutoff = now - timedelta(days=settings.agentora_missions_events_ttl_days)
        events = self.session.exec(select(WatcherEvent).order_by(WatcherEvent.created_at.desc())).all()
        deleted = 0
        kept_ids = set()

        for e in events:
            if e.event_type in IMPORTANT_EVENT_TYPES:
                kept_ids.add(e.id)

        by_run = {}
        for e in events:
            by_run.setdefault(e.run_id, []).append(e)

        for run_id, run_events in by_run.items():
            recent = run_events[: settings.agentora_missions_events_max_per_run]
            for e in recent:
                kept_ids.add(e.id)

        for e in events:
            if e.created_at < cutoff and e.id not in kept_ids:
                self.session.delete(e)
                deleted += 1

        self.session.commit()
        return {'deleted_events': deleted, 'remaining_events': len(events) - deleted}

    def export_data(self, *, start_date: datetime | None = None, end_date: datetime | None = None, repo: str | None = None, persona_id: str | None = None, status: str | None = None) -> dict:
        runs = self.list_runs(start_date=start_date, end_date=end_date, repo=repo, persona_id=persona_id, status=status, limit=10000)
        run_ids = {r.id for r in runs}
        events_q = select(WatcherEvent)
        events = [e.model_dump(mode='json') for e in self.session.exec(events_q).all() if (e.run_id in run_ids if run_ids else True)]
        alerts = [a.model_dump(mode='json') for a in self.session.exec(select(AlertEvent)).all() if (a.run_id in run_ids if run_ids else True)]
        snapshots = {r.id: self.get_snapshot(r.id) for r in runs if r.id is not None}
        return {
            'schema_version': 'mission-export-v1',
            'exported_at': datetime.utcnow().isoformat(),
            'filters': {'start_date': start_date.isoformat() if start_date else None, 'end_date': end_date.isoformat() if end_date else None, 'repo': repo, 'persona_id': persona_id, 'status': status},
            'runs': [r.model_dump(mode='json') for r in runs],
            'watcher_events': events,
            'alert_events': alerts,
            'snapshots': snapshots,
        }

    def import_data(self, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get('schema_version') != 'mission-export-v1':
            raise IntegrationClientError('Invalid import payload: schema_version mission-export-v1 required')
        runs = payload.get('runs', [])
        events = payload.get('watcher_events', [])
        alerts = payload.get('alert_events', [])
        snapshots = payload.get('snapshots', {})

        imported_runs = 0
        for item in runs:
            run_id = item.get('id')
            if run_id and self.session.get(IntegrationRun, run_id):
                continue
            row = IntegrationRun(**{k: v for k, v in item.items() if k in IntegrationRun.model_fields})
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            snap = snapshots.get(str(run_id)) or snapshots.get(run_id)
            if snap:
                row.mission_snapshot_json = dumps_json(snap)
                self.session.add(row)
                self.session.commit()
            imported_runs += 1

        imported_events = 0
        for item in events:
            evt_id = item.get('id')
            if evt_id and self.session.get(WatcherEvent, evt_id):
                continue
            evt = WatcherEvent(**{k: v for k, v in item.items() if k in WatcherEvent.model_fields})
            self.session.add(evt)
            self.session.commit()
            imported_events += 1

        imported_alerts = 0
        for item in alerts:
            alert_id = item.get('id')
            if alert_id and self.session.get(AlertEvent, alert_id):
                continue
            evt = AlertEvent(**{k: v for k, v in item.items() if k in AlertEvent.model_fields})
            self.session.add(evt)
            self.session.commit()
            imported_alerts += 1

        return {'ok': True, 'imported_runs': imported_runs, 'imported_watcher_events': imported_events, 'imported_alert_events': imported_alerts}

    def cohorts(self, *, group_by: str = 'repo', status: str | None = None, writeback_status: str | None = None, confidence_level: str | None = None, mission_score_min: int | None = None, mission_score_max: int | None = None, start_date: datetime | None = None, end_date: datetime | None = None) -> dict:
        runs = self.list_runs(status=status, writeback_status=writeback_status, confidence_level=confidence_level, mission_score_min=mission_score_min, mission_score_max=mission_score_max, start_date=start_date, end_date=end_date, limit=10000)
        valid_groups = {'repo', 'persona_id', 'status', 'writeback_status', 'confidence_level'}
        if group_by not in valid_groups:
            group_by = 'repo'
        buckets = {}
        for r in runs:
            key = getattr(r, group_by) or 'unknown'
            b = buckets.setdefault(key, {'count': 0, 'score_sum': 0.0, 'refresh_sum': 0, 'writeback_written': 0, 'terminal_success': 0, 'terminal_total': 0, 'pr_present': 0, 'risk_high': 0})
            b['count'] += 1
            b['score_sum'] += r.mission_score
            b['refresh_sum'] += r.refresh_count
            b['writeback_written'] += 1 if r.writeback_status == 'written' else 0
            b['terminal_success'] += 1 if r.status == 'completed' else 0
            b['terminal_total'] += 1 if r.status in TERMINAL_STATUSES else 0
            b['pr_present'] += 1 if r.pr_url else 0
            b['risk_high'] += 1 if r.risk_signal == 'high' else 0
        groups = []
        for key, b in buckets.items():
            c = b['count'] or 1
            groups.append({
                'group': key,
                'count': b['count'],
                'average_mission_score': b['score_sum'] / c,
                'average_refresh_count': b['refresh_sum'] / c,
                'writeback_success_rate': b['writeback_written'] / c,
                'terminal_success_rate': b['terminal_success'] / (b['terminal_total'] or 1),
                'average_pr_presence_rate': b['pr_present'] / c,
                'top_risk_signal': 'high' if b['risk_high'] > 0 else 'low_or_medium',
            })
        return {'group_by': group_by, 'groups': sorted(groups, key=lambda x: x['count'], reverse=True)}

    def cohorts_summary(self, **kwargs) -> dict:
        grouped = self.cohorts(**kwargs)
        groups = grouped['groups']
        total = sum(g['count'] for g in groups) or 1
        return {
            'group_by': grouped['group_by'],
            'total_missions': total,
            'group_count': len(groups),
            'average_mission_score': sum(g['average_mission_score'] * g['count'] for g in groups) / total,
            'average_refresh_count': sum(g['average_refresh_count'] * g['count'] for g in groups) / total,
            'writeback_success_rate': sum(g['writeback_success_rate'] * g['count'] for g in groups) / total,
            'terminal_success_rate': sum(g['terminal_success_rate'] * g['count'] for g in groups) / total,
        }
