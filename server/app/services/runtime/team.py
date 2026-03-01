from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Agent, AgentCapabilityProfile, AgentHandoff, CollaborationMetric, RunTrace, TeamPlan, TeamSubgoal
from app.services.runtime.trace import add_trace, get_run_trace


COMPLEXITY_TERMS = {'and', 'then', 'compare', 'analyze', 'design', 'build', 'verify', 'critique', 'plan', 'steps'}


def _is_complex_prompt(prompt: str) -> bool:
    p = prompt.lower()
    words = set(p.split())
    score = len(words & COMPLEXITY_TERMS) + (1 if len(prompt) > 180 else 0)
    return score >= 2


def _deliverable_for_text(text: str) -> str:
    lower = text.lower()
    if 'code' in lower or 'patch' in lower:
        return 'code_patch'
    if 'plan' in lower:
        return 'plan'
    if 'checklist' in lower:
        return 'checklist'
    if 'verify' in lower or 'test' in lower:
        return 'verification_report'
    return 'answer'


def ensure_capability_profile(session: Session, agent: Agent) -> AgentCapabilityProfile:
    profile = session.exec(select(AgentCapabilityProfile).where(AgentCapabilityProfile.agent_id == (agent.id or 0))).first()
    if profile:
        return profile
    role = (agent.role or '').lower()
    profile = AgentCapabilityProfile(
        agent_id=agent.id or 0,
        preferred_model_role='tool_planning' if 'planner' in role else 'chat',
        allowed_tools_json=agent.tools_json or '[]',
        max_tool_steps=settings.agentora_max_tool_steps,
        can_critique=('critic' in role or 'review' in role),
        can_verify=('test' in role or 'verify' in role),
        can_delegate=('lead' in role or 'planner' in role),
        can_use_workers=True,
        memory_scope='project',
        preferred_team_mode='careful' if ('critic' in role or 'verify' in role) else 'fast',
        confidence_weight=0.6,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def create_team_plan(session: Session, run_id: int, prompt: str, agents: list[Agent], requested_mode: str | None = None) -> TeamPlan:
    mode = requested_mode or settings.agentora_default_team_mode
    complex_prompt = _is_complex_prompt(prompt)
    use_single = settings.agentora_enable_single_agent_fallback and not complex_prompt

    plan = TeamPlan(
        run_id=run_id,
        goal=prompt,
        mode='single_agent' if use_single else mode,
        status='active',
        confidence=0.72 if complex_prompt else 0.85,
        urgency=0.6,
        priority=0.7,
        revision=1,
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    if use_single or len(agents) <= 1:
        primary = agents[0] if agents else None
        session.add(
            TeamSubgoal(
                plan_id=plan.id or 0,
                run_id=run_id,
                title='Handle user request directly',
                detail=prompt,
                assigned_agent_id=primary.id if primary else None,
                assigned_agent_role=primary.role if primary else 'assistant',
                status='pending',
                needs_worker=False,
                deliverable_type=_deliverable_for_text(prompt),
                confidence=0.82,
                urgency=0.5,
                priority=1.0,
                max_steps=min(3, settings.agentora_max_tool_steps),
            )
        )
    else:
        steps = [
            ('Plan approach', f'Create concise plan for: {prompt}', 'planner'),
            ('Execute draft output', f'Produce draft response for: {prompt}', 'executor'),
        ]
        if settings.agentora_enable_team_debate:
            steps.append(('Critique draft', f'Critique and verify draft for: {prompt}', 'critic'))
        steps.append(('Synthesize final', f'Synthesize final deliverable for: {prompt}', 'synthesizer'))

        for idx, (title, detail, role_hint) in enumerate(steps):
            assigned = next((a for a in agents if role_hint in (a.role or '').lower()), agents[idx % len(agents)])
            session.add(
                TeamSubgoal(
                    plan_id=plan.id or 0,
                    run_id=run_id,
                    parent_subgoal_id=None,
                    title=title,
                    detail=detail,
                    assigned_agent_id=assigned.id,
                    assigned_agent_role=assigned.role,
                    dependency_subgoal_ids_json=json.dumps([idx - 1] if idx > 0 else []),
                    status='pending',
                    needs_worker=('execute' in title.lower()),
                    deliverable_type=_deliverable_for_text(detail),
                    confidence=0.7,
                    urgency=0.6,
                    priority=max(0.3, 1.0 - idx * 0.1),
                    max_steps=min(settings.agentora_max_team_turns, settings.agentora_max_tool_steps + 1),
                )
            )

    session.commit()
    add_trace(session, run_id, 'team_plan_created', {'plan_id': plan.id, 'mode': plan.mode, 'single_agent': use_single, 'goal': prompt[:280]}, agent_id=0)
    session.commit()
    return plan


def list_plan(session: Session, run_id: int) -> dict:
    plan = session.exec(select(TeamPlan).where(TeamPlan.run_id == run_id).order_by(TeamPlan.id.desc())).first()
    if not plan:
        return {'ok': False, 'error': 'plan_not_found'}
    subgoals = list(session.exec(select(TeamSubgoal).where(TeamSubgoal.plan_id == plan.id).order_by(TeamSubgoal.id)))
    return {'ok': True, 'plan': plan, 'subgoals': subgoals}


def create_handoff(
    session: Session,
    run_id: int,
    from_agent_id: int,
    to_agent_id: int,
    reason: str,
    context: str,
    expected_output: str,
    allow_tools: bool,
    allow_memory: bool,
    max_steps: int,
) -> AgentHandoff:
    handoff = AgentHandoff(
        run_id=run_id,
        from_agent_id=from_agent_id,
        to_agent_id=to_agent_id,
        reason=reason,
        context_json=json.dumps({'context': context[:1200]}),
        expected_output=expected_output,
        allow_tools=allow_tools,
        allow_memory=allow_memory,
        max_steps=max_steps,
        status='open',
        deadline_at=datetime.utcnow(),
    )
    session.add(handoff)
    session.commit()
    session.refresh(handoff)
    add_trace(session, run_id, 'agent_handoff', {'handoff_id': handoff.id, 'from_agent_id': from_agent_id, 'to_agent_id': to_agent_id, 'reason': reason, 'expected_output': expected_output}, agent_id=from_agent_id)
    session.commit()
    return handoff


def complete_handoff(session: Session, handoff_id: int, accepted: bool = True, escalated: bool = False) -> AgentHandoff | None:
    handoff = session.get(AgentHandoff, handoff_id)
    if not handoff:
        return None
    if not accepted:
        handoff.status = 'rejected'
        add_trace(session, handoff.run_id, 'handoff_rejected', {'handoff_id': handoff.id, 'to_agent_id': handoff.to_agent_id}, agent_id=handoff.to_agent_id)
    elif escalated:
        handoff.status = 'escalated'
        add_trace(session, handoff.run_id, 'handoff_escalated', {'handoff_id': handoff.id}, agent_id=handoff.to_agent_id)
    else:
        handoff.status = 'completed'
        add_trace(session, handoff.run_id, 'handoff_completed', {'handoff_id': handoff.id}, agent_id=handoff.to_agent_id)
    handoff.updated_at = datetime.utcnow()
    session.add(handoff)
    session.commit()
    return handoff


def record_collaboration_metrics(session: Session, run_id: int) -> CollaborationMetric:
    trace = get_run_trace(session, run_id)
    count = lambda e: sum(1 for t in trace if t['event_type'] == e)
    handoffs = count('agent_handoff')
    completed = count('handoff_completed')
    fallback = count('worker_route_fallback')
    selected = count('worker_route_selected')
    synth_done = count('synthesis_completed')
    subgoal_assigned = count('subgoal_assigned')
    subgoal_completed = count('subgoal_completed')

    metric = session.exec(select(CollaborationMetric).where(CollaborationMetric.run_id == run_id)).first()
    if not metric:
        metric = CollaborationMetric(run_id=run_id)
    metric.handoff_success_rate = (completed / handoffs) if handoffs else 1.0
    metric.worker_route_success_rate = (selected / max(1, selected + fallback))
    metric.final_synthesis_completeness = 1.0 if synth_done else 0.6
    metric.plan_execution_consistency = (subgoal_completed / max(1, subgoal_assigned))
    metric.no_progress_terminations = count('warning')
    metric.updated_at = datetime.utcnow()
    session.add(metric)
    session.commit()
    session.refresh(metric)
    return metric


def collaboration_trace(session: Session, run_id: int) -> list[dict]:
    interesting = {
        'team_plan_created', 'team_plan_revised', 'subgoal_assigned', 'subgoal_completed',
        'agent_handoff', 'handoff_rejected', 'handoff_completed', 'handoff_escalated',
        'debate_started', 'critique_issued', 'verification_failed', 'synthesis_completed',
        'worker_route_selected', 'worker_route_fallback', 'worker_route_rejected',
    }
    return [t for t in get_run_trace(session, run_id) if t['event_type'] in interesting]
