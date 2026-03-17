import json
from datetime import datetime, timedelta

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
from app.models import IntegrationRun, WatcherEvent

ACTIVE_STATUSES = {'preparing_launch', 'launched', 'running', 'queued'}
TERMINAL_STATUSES = {'completed', 'failed', 'cancelled', 'error'}


class IntegrationOrchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.phios = PhiOSClient()
        self.agentception = AgentCeptionClient()

    def _to_record(self, row: IntegrationRun) -> OrchestrationRunRecord:
        return OrchestrationRunRecord.model_validate(row.model_dump())

    def _parse_json_list(self, raw: str) -> list:
        try:
            value = json.loads(raw or '[]')
            return value if isinstance(value, list) else []
        except Exception:
            return []

    def _log_event(self, event_type: str, *, run_id: int | None = None, status: str = '', latency_ms: float = 0.0, detail: dict | None = None):
        evt = WatcherEvent(run_id=run_id, event_type=event_type, status=status, latency_ms=latency_ms, detail_json=dumps_json(detail or {}))
        self.session.add(evt)
        self.session.commit()

    def _evaluate_run(self, row: IntegrationRun, outcome: AgentExecutionOutcome | None = None) -> None:
        score = 0
        if row.status in TERMINAL_STATUSES:
            score += 30
        if row.pr_url:
            score += 25
        if self._parse_json_list(row.issue_urls_json):
            score += 10
        if self._parse_json_list(row.artifact_urls_json):
            score += 10
        if len((row.summary or '').strip()) >= 80:
            score += 15
        if row.writeback_status == 'written':
            score += 10
        if row.writeback_status == 'failed':
            score -= 10
        score = max(0, min(100, score))
        row.mission_score = score
        row.confidence_level = 'high' if score >= 75 else ('medium' if score >= 45 else 'low')
        row.completion_signal = 'terminal' if row.status in TERMINAL_STATUSES else 'in_progress'
        row.result_quality_signal = 'high' if len((row.summary or '').strip()) >= 120 else ('medium' if len((row.summary or '').strip()) >= 40 else 'low')
        readiness = is_meaningful_outcome(outcome) if outcome else bool(row.summary)
        row.writeback_readiness_signal = 'high' if readiness else 'low'
        failure_like = row.status in {'failed', 'error'} or row.writeback_status == 'failed'
        row.risk_signal = 'high' if failure_like else ('medium' if row.status in {'running', 'launched'} else 'low')

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
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            self._log_event('launched', run_id=row.id, status=launch.status)
            self.session.refresh(row)
            return self._to_record(row)
        except Exception as exc:
            row.status = 'error'
            row.updated_at = datetime.utcnow()
            row.error_message = str(exc)
            self._evaluate_run(row)
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            self._log_event('launched', run_id=row.id, status='error', detail={'error': str(exc)})
            self.session.refresh(row)
            return self._to_record(row)

    def run_software_task_with_context(self, persona_id: str, repo: str, objective: str, acceptance_criteria: list[str], constraints: list[str], dry_run: bool) -> OrchestrationRunRecord:
        return self.launch_software_mission(LaunchMissionRequest(persona_id=persona_id, repo=repo, mission_title=objective[:80], objective=objective, acceptance_criteria=acceptance_criteria, constraints=constraints, dry_run=dry_run))

    def launch_from_request(self, payload: SoftwareTaskRequest) -> OrchestrationRunRecord:
        return self.launch_software_mission(LaunchMissionRequest(**payload.model_dump(mode='json')))

    def list_runs(self, *, status: str | None = None, repo: str | None = None, persona_id: str | None = None, writeback_status: str | None = None, start_date: datetime | None = None, end_date: datetime | None = None, search: str | None = None, limit: int = 50, offset: int = 0, watch_enabled_only: bool = False) -> list[OrchestrationRunRecord]:
        q = select(IntegrationRun)
        if status:
            q = q.where(IntegrationRun.status == status)
        if repo:
            q = q.where(IntegrationRun.repo.contains(repo))
        if persona_id:
            q = q.where(IntegrationRun.persona_id.contains(persona_id))
        if writeback_status:
            q = q.where(IntegrationRun.writeback_status == writeback_status)
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

    def list_watcher_events(self, limit: int = 100) -> list[dict]:
        rows = self.session.exec(select(WatcherEvent).order_by(WatcherEvent.created_at.desc()).limit(limit)).all()
        return [r.model_dump() for r in rows]

    def get_metrics(self) -> dict:
        rows = self.session.exec(select(WatcherEvent)).all()
        latency = [r.latency_ms for r in rows if r.latency_ms > 0]
        def count(ev: str):
            return sum(1 for r in rows if r.event_type == ev)
        watched = len(self.list_active_runs_for_watcher(settings.agentora_missions_watcher_max_active_runs))
        return {
            'refresh_attempts': count('refresh_attempt'),
            'refresh_successes': count('refreshed') + count('watcher_refreshed'),
            'refresh_failures': count('refresh_failed'),
            'average_refresh_latency_ms': (sum(latency) / len(latency)) if latency else 0.0,
            'last_refresh_latency_ms': latency[-1] if latency else 0.0,
            'skipped_writebacks_debounce': count('writeback_skipped_debounce'),
            'skipped_writebacks_duplicate_hash': count('writeback_skipped_duplicate_hash'),
            'successful_writebacks': count('writeback_succeeded'),
            'failed_writebacks': count('writeback_failed'),
            'runs_currently_watched': watched,
            'terminal_runs_completed_by_watcher': count('terminal_state_reached'),
        }

    def get_insights(self) -> dict:
        runs = self.session.exec(select(IntegrationRun)).all()
        by_status: dict[str, int] = {}
        by_persona: dict[str, int] = {}
        by_repo: dict[str, int] = {}
        for r in runs:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            by_persona[r.persona_id] = by_persona.get(r.persona_id, 0) + 1
            by_repo[r.repo] = by_repo.get(r.repo, 0) + 1
        total = len(runs) or 1
        writeback_written = sum(1 for r in runs if r.writeback_status == 'written')
        terminal_success = sum(1 for r in runs if r.status == 'completed')
        terminal_total = sum(1 for r in runs if r.status in TERMINAL_STATUSES) or 1
        avg_score = sum(r.mission_score for r in runs) / total
        avg_refresh_by_status = {s: (sum(r.refresh_count for r in runs if r.status == s) / c) for s, c in by_status.items()}
        top_repos = sorted(by_repo.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            'missions_by_status': by_status,
            'missions_by_persona': by_persona,
            'writeback_success_rate': writeback_written / total,
            'average_watcher_refresh_count_by_status': avg_refresh_by_status,
            'top_repos_by_mission_count': top_repos,
            'terminal_success_rate': terminal_success / terminal_total,
            'average_mission_score': avg_score,
        }

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
                self._log_event('terminal_state_reached', run_id=run_id, status=row.status)
            self._evaluate_run(row, outcome)
            self.session.add(row)
            self.session.commit()

            if source == 'watcher' and row.auto_writeback_enabled:
                self._maybe_auto_writeback(row, outcome, outcome_hash)

            latency_ms = (datetime.utcnow() - t0).total_seconds() * 1000
            self._log_event('watcher_refreshed' if source == 'watcher' else 'refreshed', run_id=run_id, status=row.status, latency_ms=latency_ms)
            self.session.refresh(row)
            return self._to_record(row)
        except Exception as exc:
            row.watch_error = str(exc)
            self.session.add(row)
            self.session.commit()
            latency_ms = (datetime.utcnow() - t0).total_seconds() * 1000
            self._log_event('refresh_failed', run_id=run_id, status='error', latency_ms=latency_ms, detail={'error': str(exc)})
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
            self._log_event('writeback_skipped_debounce', run_id=row.id, status=row.status)
            return
        if row.writeback_status == 'written' and row.last_writeback_hash == outcome_hash:
            self._log_event('writeback_skipped_duplicate_hash', run_id=row.id, status=row.status)
            return
        try:
            self._perform_writeback(row, outcome, operator_notes='auto-writeback from watcher', tags=['phase-e', 'auto'])
        except Exception:
            pass

    def _perform_writeback(self, row: IntegrationRun, outcome: AgentExecutionOutcome, operator_notes: str, tags: list[str] | None) -> dict:
        payload = map_outcome_to_writeback_payload(session_id=row.phios_session_id, task_id=row.agentception_job_id or f'run-{row.id}', repo=row.repo, objective=row.objective, outcome=outcome, tags=tags, operator_notes=operator_notes)
        row.last_writeback_attempt_at = datetime.utcnow()
        self.session.add(row)
        self.session.commit()
        self._log_event('writeback_attempted', run_id=row.id, status=row.status)
        try:
            result = self.phios.write_mission_result(payload)
            outcome_hash = outcome_fingerprint(outcome)
            row.writeback_status = 'written'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = ''
            row.last_writeback_hash = outcome_hash
            self._evaluate_run(row, outcome)
            self.session.add(row)
            self.session.commit()
            self._log_event('writeback_succeeded', run_id=row.id, status=row.status)
            return {'ok': True, 'result': result}
        except Exception as exc:
            row.writeback_status = 'failed'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = str(exc)
            self._evaluate_run(row, outcome)
            self.session.add(row)
            self.session.commit()
            self._log_event('writeback_failed', run_id=row.id, status=row.status, detail={'error': str(exc)})
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

    def run_timeline(self, run_id: int) -> list[dict]:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        events = [
            {'event': 'prepared', 'at': row.created_at.isoformat(), 'status': 'ok'},
            {'event': 'launched', 'at': row.updated_at.isoformat(), 'status': row.agentception_status, 'job_id': row.agentception_job_id},
        ]
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
            try:
                return json.loads(r.agentception_result_json or '{}').get('phase', '')
            except Exception:
                return ''

        def packet_list(r: IntegrationRun, key: str) -> list[str]:
            try:
                packet = json.loads(r.phios_packet_json or '{}')
                value = packet.get(key, [])
                if isinstance(value, list):
                    items = []
                    for item in value:
                        if isinstance(item, dict):
                            items.append(item.get('name') or item.get('text') or json.dumps(item))
                        else:
                            items.append(str(item))
                    return items
            except Exception:
                pass
            return []

        diffs = {}
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
        for k, (l, r) in fields.items():
            if l != r:
                diffs[k] = {'left': l, 'right': r}

        left_followups = self._parse_json_list(left.recommended_actions_json)
        right_followups = self._parse_json_list(right.recommended_actions_json)
        left_success = self._parse_json_list(left.success_criteria_json)
        right_success = self._parse_json_list(right.success_criteria_json)
        left_risks = packet_list(left, 'risk_flags')
        right_risks = packet_list(right, 'risk_flags')
        left_timeline = self.run_timeline(left_run_id)
        right_timeline = self.run_timeline(right_run_id)

        interpretation = 'Runs are broadly aligned.'
        if diffs:
            interpretation = f"Runs differ across {len(diffs)} key fields; review status/phase and writeback posture before deciding next action."
        if left.status in TERMINAL_STATUSES and right.status not in TERMINAL_STATUSES:
            interpretation = 'Left run appears more mature/terminal than right run.'

        return {
            'left': {'id': left.id, 'mission_title': left.mission_title, 'repo': left.repo, 'status': left.status, 'pr_url': left.pr_url, 'summary': left.summary, 'recommended_followups': left_followups, 'writeback_status': left.writeback_status},
            'right': {'id': right.id, 'mission_title': right.mission_title, 'repo': right.repo, 'status': right.status, 'pr_url': right.pr_url, 'summary': right.summary, 'recommended_followups': right_followups, 'writeback_status': right.writeback_status},
            'field_differences': diffs,
            'summary_similarity_note': 'same' if (left.summary or '').strip() == (right.summary or '').strip() else 'different',
            'recommended_followups_delta': {'only_left': [x for x in left_followups if x not in right_followups], 'only_right': [x for x in right_followups if x not in left_followups]},
            'success_criteria_delta': {'only_left': [x for x in left_success if x not in right_success], 'only_right': [x for x in right_success if x not in left_success]},
            'risk_flags_delta': {'only_left': [x for x in left_risks if x not in right_risks], 'only_right': [x for x in right_risks if x not in left_risks]},
            'outcome_hash_equal': left.last_outcome_hash == right.last_outcome_hash,
            'timeline_length_comparison': {'left': len(left_timeline), 'right': len(right_timeline)},
            'interpretation': interpretation,
        }
