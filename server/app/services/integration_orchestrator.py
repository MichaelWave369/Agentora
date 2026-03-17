import json
from datetime import datetime

from sqlmodel import Session, select

from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import IntegrationClientError, PhiOSClient
from app.integrations.schemas import (
    AgentCeptionLaunchRequest,
    ContextPackRequest,
    MemoryWriteRequest,
    OrchestrationRunRecord,
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

    def run_software_task_with_context(
        self,
        persona_id: str,
        repo: str,
        objective: str,
        acceptance_criteria: list[str],
        constraints: list[str],
        dry_run: bool,
    ) -> OrchestrationRunRecord:
        row = IntegrationRun(
            status='initializing',
            persona_id=persona_id,
            repo=repo,
            objective=objective,
            raw_payload_json='{}',
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)

        try:
            context = self.phios.get_context_pack(
                ContextPackRequest(persona_id=persona_id, task='software_mission', repo=repo, objective=objective, limit=6)
            )
            launch_request = AgentCeptionLaunchRequest(
                title=objective[:120],
                repo=repo,
                objective=objective,
                context_summary=context.summary,
                acceptance_criteria=acceptance_criteria,
                constraints=list(dict.fromkeys(constraints + context.constraints)),
                persona_name=context.persona.name,
                persona_role=context.persona.role,
                memory_snippets=[m.text for m in context.memory_snippets],
                dry_run=dry_run,
            )
            launch = self.agentception.launch_job(launch_request)

            row.status = 'launched'
            row.updated_at = datetime.utcnow()
            row.phios_session_id = context.session_id
            row.agentception_job_id = launch.job_id
            row.agentception_status = launch.status
            row.summary = launch.message
            row.raw_payload_json = json.dumps(
                {
                    'context_pack': context.model_dump(mode='json'),
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

    def launch_from_request(self, payload: SoftwareTaskRequest) -> OrchestrationRunRecord:
        return self.run_software_task_with_context(
            persona_id=payload.persona_id,
            repo=payload.repo,
            objective=payload.objective,
            acceptance_criteria=payload.acceptance_criteria,
            constraints=payload.constraints,
            dry_run=payload.dry_run,
        )

    def list_runs(self) -> list[OrchestrationRunRecord]:
        rows = self.session.exec(select(IntegrationRun).order_by(IntegrationRun.created_at.desc())).all()
        return [self._to_record(r) for r in rows]

    def get_run(self, run_id: int) -> OrchestrationRunRecord | None:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            return None
        return self._to_record(row)

    def refresh_run(self, run_id: int) -> OrchestrationRunRecord:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.agentception_job_id:
            raise IntegrationClientError('Run has no AgentCeption job id yet')
        status = self.agentception.get_job_status(row.agentception_job_id)
        row.updated_at = datetime.utcnow()
        row.status = 'running' if status.status not in {'failed', 'completed'} else status.status
        row.agentception_status = status.status
        row.pr_url = status.pr_url
        row.summary = status.summary or row.summary
        if row.raw_payload_json:
            payload = json.loads(row.raw_payload_json)
        else:
            payload = {}
        payload['last_status'] = status.model_dump(mode='json')
        row.raw_payload_json = json.dumps(payload)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return self._to_record(row)

    def writeback_run(self, run_id: int, summary: str = '', details: str = '', tags: list[str] | None = None) -> dict:
        row = self.session.get(IntegrationRun, run_id)
        if not row:
            raise IntegrationClientError(f'Run {run_id} not found')
        if not row.phios_session_id:
            raise IntegrationClientError('Run has no PhiOS session id yet')
        result = self.phios.write_memory(
            MemoryWriteRequest(
                session_id=row.phios_session_id,
                source_system='agentora',
                task_id=row.agentception_job_id or f'run-{row.id}',
                summary=summary or row.summary or 'Integration run update',
                details=details or row.raw_payload_json,
                tags=tags or ['agentora', 'agentception', row.status],
            )
        )
        return {'ok': True, 'result': result}
