import json
from datetime import datetime, timezone
from typing import Any

from app.integrations.schemas import (
    AgentCeptionJobStatus,
    AgentCeptionLaunchRequest,
    AgentExecutionOutcome,
    MissionContextPacket,
    MissionWritebackPayload,
)


def _truncate(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + '...'


def map_packet_to_launch_request(
    packet: MissionContextPacket,
    acceptance_criteria: list[str],
    constraints: list[str],
    dry_run: bool,
) -> AgentCeptionLaunchRequest:
    memory = [_truncate(item.text, 220) for item in packet.memory_snippets[:12]]
    merged_constraints = list(dict.fromkeys([*constraints, *packet.constraints]))[:30]
    return AgentCeptionLaunchRequest(
        mission_title=_truncate(packet.mission_title, 160),
        repo=packet.repo,
        objective=_truncate(packet.mission_objective, 1200),
        operator_intent=_truncate(packet.operator_intent, 500),
        context_summary=_truncate(packet.summary, 1400),
        dispatch_brief=packet.dispatch_brief.model_dump(mode='json'),
        acceptance_criteria=[_truncate(c, 240) for c in acceptance_criteria[:30]],
        constraints=[_truncate(c, 240) for c in merged_constraints],
        persona_name=packet.persona.name,
        persona_role=packet.persona.role,
        persona_style=packet.persona.style,
        memory_snippets=memory,
        coding_style_preferences=[x.model_dump(mode='json') for x in packet.coding_style_preferences[:20]],
        architectural_principles=[x.model_dump(mode='json') for x in packet.architectural_principles[:20]],
        risk_flags=[x.model_dump(mode='json') for x in packet.risk_flags[:20]],
        recommended_next_actions=[_truncate(x, 240) for x in packet.recommended_next_actions[:20]],
        success_criteria=[x.model_dump(mode='json') for x in packet.success_criteria[:20]],
        dry_run=dry_run,
    )


def normalize_job_status(status: AgentCeptionJobStatus, raw_payload: dict[str, Any] | None = None) -> AgentExecutionOutcome:
    is_done = status.status in {'completed', 'failed', 'cancelled'}
    return AgentExecutionOutcome(
        job_id=status.job_id,
        status=status.status,
        phase=status.phase,
        branch=status.branch,
        pr_url=status.pr_url,
        issue_urls=status.issue_urls,
        artifact_urls=status.artifact_urls,
        summary=status.summary,
        result_kind='final' if is_done else 'status_update',
        completed_at=datetime.now(timezone.utc) if is_done else None,
        raw_status_payload=raw_payload or status.model_dump(mode='json'),
    )


def map_outcome_to_writeback_payload(
    *,
    session_id: str,
    task_id: str,
    repo: str,
    objective: str,
    outcome: AgentExecutionOutcome,
    tags: list[str] | None = None,
    operator_notes: str = '',
) -> MissionWritebackPayload:
    followups: list[str] = []
    if outcome.status not in {'completed'}:
        followups.append('Re-run refresh and validate downstream execution state')
    if outcome.pr_url:
        followups.append('Review PR and merge policy checks')
    return MissionWritebackPayload(
        session_id=session_id,
        source_system='agentora',
        task_id=task_id,
        repo=repo,
        objective=objective,
        outcome_status=outcome.status,
        summary=outcome.summary or f'Job {outcome.job_id} status: {outcome.status}',
        branch=outcome.branch,
        pr_url=outcome.pr_url,
        issue_urls=outcome.issue_urls,
        artifact_urls=outcome.artifact_urls,
        recommended_followups=followups,
        operator_notes=operator_notes,
        tags=tags or ['agentora', 'phase-c', outcome.status],
        raw_payload={'outcome': outcome.model_dump(mode='json')},
    )


def dumps_json(data: Any) -> str:
    return json.dumps(data, default=str)
