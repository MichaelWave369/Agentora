from datetime import datetime

from sqlmodel import Session, select

from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.mappers import (
    dumps_json,
    map_outcome_to_writeback_payload,
    map_packet_to_launch_request,
    normalize_job_status,
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
from app.models import IntegrationRun


class IntegrationOrchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.phios = PhiOSClient()
        self.agentception = AgentCeptionClient()

    def _to_record(self, row: IntegrationRun) -> OrchestrationRunRecord:
        return OrchestrationRunRecord.model_validate(row.model_dump())

    def prepare_mission_context(self, payload: PrepareMissionRequest) -> MissionContextPacket:
        return self.phios.get_context_pack(
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
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)

        try:
            launch = self.agentception.launch_job(launch_request)
            row.status = 'launched'
            row.updated_at = datetime.utcnow()
            row.agentception_job_id = launch.job_id
            row.agentception_status = launch.status
            row.summary = launch.message
            row.raw_payload_json = dumps_json(
                {
                    'phios_packet': packet.model_dump(mode='json'),
                    'launch_request': launch_request.model_dump(mode='json'),
                    'launch_response': launch.model_dump(mode='json'),
                }
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return self._to_record(row)
        except Exception as exc:
            row.status = 'error'
            row.updated_at = datetime.utcnow()
            row.error_message = str(exc)
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return self._to_record(row)

    def run_software_task_with_context(
        self,
        persona_id: str,
        repo: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str],
        dry_run: bool,
    ) -> OrchestrationRunRecord:
        return self.launch_software_mission(
            LaunchMissionRequest(
                persona_id=persona_id,
                repo=repo,
                mission_title=objective[:80],
                objective=objective,
                acceptance_criteria=acceptance_criteria,
                constraints=constraints,
                dry_run=dry_run,
            )
        )

    def launch_from_request(self, payload: SoftwareTaskRequest) -> OrchestrationRunRecord:
        return self.launch_software_mission(LaunchMissionRequest(**payload.model_dump(mode='json')))

    def list_runs(self, limit: int = 50) -> list[OrchestrationRunRecord]:
        rows = self.session.exec(select(IntegrationRun).order_by(IntegrationRun.created_at.desc()).limit(limit)).all()
        return [self._to_record(r) for r in rows]

    def get_run(self, run_id: int) -> OrchestrationRunRecord | None:
        row = self.session.get(IntegrationRun, run_id)
        return self._to_record(row) if row else None

    def refresh_run(self, run_id: int) -> OrchestrationRunRecord:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.agentception_job_id:
            raise IntegrationClientError('Run has no AgentCeption job id yet')
        status = self.agentception.get_job_status(row.agentception_job_id)
        outcome: AgentExecutionOutcome = normalize_job_status(status)

        row.updated_at = datetime.utcnow()
        row.status = 'running' if outcome.status not in {'failed', 'completed', 'cancelled'} else outcome.status
        row.agentception_status = outcome.status
        row.branch = outcome.branch or row.branch
        row.pr_url = outcome.pr_url or row.pr_url
        if outcome.issue_urls:
            row.issue_urls_json = dumps_json(outcome.issue_urls)
        if outcome.artifact_urls:
            row.artifact_urls_json = dumps_json(outcome.artifact_urls)
        row.summary = outcome.summary or row.summary
        row.agentception_result_json = dumps_json(outcome.model_dump(mode='json'))
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_record(row)

    def writeback_run(self, run_id: int, operator_notes: str = '', tags: list[str] | None = None) -> dict:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.phios_session_id:
            raise IntegrationClientError('Run has no PhiOS session id yet')

        if row.agentception_result_json:
            outcome = AgentExecutionOutcome.model_validate_json(row.agentception_result_json)
        else:
            outcome = AgentExecutionOutcome(
                job_id=row.agentception_job_id or f'run-{row.id}',
                status=row.agentception_status or row.status,
                phase='',
                branch=row.branch,
                pr_url=row.pr_url,
                issue_urls=[],
                artifact_urls=[],
                summary=row.summary,
            )
        payload = map_outcome_to_writeback_payload(
            session_id=row.phios_session_id,
            task_id=row.agentception_job_id or f'run-{row.id}',
            repo=row.repo,
            objective=row.objective,
            outcome=outcome,
            tags=tags,
            operator_notes=operator_notes,
        )
        try:
            result = self.phios.write_mission_result(payload)
            row.writeback_status = 'written'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = ''
            self.session.add(row)
            self.session.commit()
            return {'ok': True, 'result': result}
        except Exception as exc:
            row.writeback_status = 'failed'
            row.writeback_at = datetime.utcnow()
            row.writeback_error = str(exc)
            self.session.add(row)
            self.session.commit()
            raise

    def run_timeline(self, run_id: int) -> list[dict]:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        events = [
            {'event': 'created', 'at': row.created_at.isoformat(), 'status': row.status},
            {'event': 'launch', 'at': row.updated_at.isoformat(), 'job_id': row.agentception_job_id, 'agentception_status': row.agentception_status},
        ]
        if row.pr_url:
            events.append({'event': 'pr_opened', 'at': row.updated_at.isoformat(), 'pr_url': row.pr_url})
        if row.writeback_at:
            events.append({'event': 'writeback', 'at': row.writeback_at.isoformat(), 'writeback_status': row.writeback_status})
        return events
