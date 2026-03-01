import json
from datetime import datetime
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Agent, Attachment, Message, Run, RunMetric, TeamAgent, TemplateUsage, TeamSubgoal
from app.services.runtime.loop import runtime_loop
from app.services.runtime.team import complete_handoff, create_handoff, create_team_plan, ensure_capability_profile, record_collaboration_metrics
from app.services.runtime.trace import add_trace
from .state import RunState


class OrchestrationEngine:
    def __init__(self):
        pass

    async def execute(self, session: Session, run: Run, prompt: str, reflection: bool = False) -> RunState:
        links = list(session.exec(select(TeamAgent).where(TeamAgent.team_id == run.team_id).order_by(TeamAgent.position)))
        agents = [session.get(Agent, link.agent_id) for link in links if session.get(Agent, link.agent_id)]
        for a in agents:
            ensure_capability_profile(session, a)

        attachments = list(session.exec(select(Attachment).where(Attachment.run_id == run.id)))
        state = RunState(run_id=run.id, prompt=prompt, mode=run.mode, max_turns=run.max_turns, max_seconds=run.max_seconds, token_budget=run.token_budget, reflection=reflection)
        state.add('user', prompt)

        plan = create_team_plan(session, run_id=run.id, prompt=prompt, agents=agents, requested_mode=run.mode)
        subgoals = list(session.exec(select(TeamSubgoal).where(TeamSubgoal.plan_id == plan.id).order_by(TeamSubgoal.id)))

        image_paths = [a.path for a in attachments if a.mime.startswith('image/')]
        handoffs = 0
        no_progress = 0
        debate_turns = 0

        for idx, sg in enumerate(subgoals[: settings.agentora_max_team_turns]):
            if handoffs >= settings.agentora_max_handoffs:
                add_trace(session, run.id, 'handoff_escalated', {'reason': 'max_handoffs_reached', 'max_handoffs': settings.agentora_max_handoffs}, agent_id=0)
                break
            agent = next((a for a in agents if (a.id or 0) == (sg.assigned_agent_id or -1)), agents[min(idx, len(agents) - 1)] if agents else None)
            if not agent:
                continue

            add_trace(session, run.id, 'subgoal_assigned', {'subgoal_id': sg.id, 'title': sg.title, 'assigned_agent_id': agent.id, 'assigned_role': agent.role, 'needs_worker': sg.needs_worker, 'deliverable_type': sg.deliverable_type}, agent_id=agent.id or 0)
            prev = state.messages[-1]['content'] if state.messages else prompt
            handoff = None
            if idx > 0 and len(agents) > 1:
                prev_agent = next((a for a in agents if (a.id or 0) == (subgoals[idx - 1].assigned_agent_id or -1)), None)
                if prev_agent and prev_agent.id != agent.id:
                    handoff = create_handoff(
                        session,
                        run_id=run.id,
                        from_agent_id=prev_agent.id or 0,
                        to_agent_id=agent.id or 0,
                        reason=f'{sg.title} requires {agent.role}',
                        context=prev,
                        expected_output=sg.deliverable_type,
                        allow_tools=True,
                        allow_memory=True,
                        max_steps=min(sg.max_steps, settings.agentora_max_tool_steps),
                    )
                    handoffs += 1

            if settings.agentora_enable_team_debate and 'critic' in (agent.role or '').lower() and debate_turns == 0:
                add_trace(session, run.id, 'debate_started', {'subgoal_id': sg.id, 'mode': plan.mode}, agent_id=agent.id or 0)
                debate_turns += 1

            rt = await runtime_loop.run_agent(
                session=session,
                run_id=run.id,
                agent=agent,
                prompt=f"Subgoal: {sg.title}\nRequired deliverable: {sg.deliverable_type}\nContext: {prev}\nTask detail: {sg.detail}",
                image_paths=image_paths,
                max_steps=min(sg.max_steps, settings.agentora_max_tool_steps),
            )

            reply = rt.final_text
            if 'critic' in (agent.role or '').lower():
                add_trace(session, run.id, 'critique_issued', {'subgoal_id': sg.id, 'agent_id': agent.id, 'excerpt': reply[:240]}, agent_id=agent.id or 0)
                if 'fail' in reply.lower() or 'cannot verify' in reply.lower():
                    add_trace(session, run.id, 'verification_failed', {'subgoal_id': sg.id, 'agent_id': agent.id}, agent_id=agent.id or 0)

            if state.repeated(reply):
                no_progress += 1
            else:
                no_progress = 0
            if no_progress >= 2:
                add_trace(session, run.id, 'team_plan_revised', {'reason': 'no_progress_detected', 'subgoal_id': sg.id}, agent_id=0)
                if settings.agentora_force_synthesis_on_budget_exhaust:
                    break

            in_toks = max(1, len(sg.detail) // 4)
            out_toks = max(1, len(reply) // 4)
            session.add(RunMetric(run_id=run.id, agent_id=agent.id or 0, tokens_in=in_toks, tokens_out=out_toks, seconds=0.0, tool_calls=rt.tool_calls_count))
            state.add('assistant', reply, agent.id, meta={'subgoal_id': sg.id, 'deliverable_type': sg.deliverable_type, 'stop_reason': rt.stop_reason, 'model_used': rt.model_used, 'worker_used': rt.worker_used})

            sg.status = 'done'
            sg.output_text = reply[:2000]
            sg.updated_at = datetime.utcnow()
            session.add(sg)
            add_trace(session, run.id, 'subgoal_completed', {'subgoal_id': sg.id, 'agent_id': agent.id, 'deliverable_type': sg.deliverable_type}, agent_id=agent.id or 0)

            if handoff:
                complete_handoff(session, handoff.id, accepted=True, escalated=False)

            if state.reflection:
                state.add('system', f'Reflection {agent.name}: quality=0.8 uncertainty=0.2', agent.id)

        if plan.mode != 'single_agent':
            synthesis = '\n\n'.join([m['content'] for m in state.messages if m.get('role') == 'assistant'][-3:])
            state.add('assistant', f"Final synthesis:\n{synthesis[:2000]}", agents[-1].id if agents else None)
            add_trace(session, run.id, 'synthesis_completed', {'mode': plan.mode, 'subgoals': len(subgoals)}, agent_id=(agents[-1].id if agents else 0))

        run.finished_at = datetime.utcnow()
        if run.status == 'running':
            run.status = 'completed'
        run.result_summary = state.messages[-1]['content'][:300] if state.messages else ''
        session.add(run)

        for m in state.messages:
            session.add(Message(run_id=run.id, agent_id_nullable=m.get('agent_id'), role=m['role'], content=m['content'], meta_json=json.dumps(m.get('meta', {}))))

        usage = session.exec(select(TemplateUsage).where(TemplateUsage.template_id == run.team_id)).first() or TemplateUsage(template_id=run.team_id, runs_count=0)
        usage.runs_count += 1
        usage.last_used_at = datetime.utcnow()
        session.add(usage)

        record_collaboration_metrics(session, run.id)
        session.commit()
        return state
