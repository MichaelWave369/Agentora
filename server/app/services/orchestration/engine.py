import asyncio
import json
from datetime import datetime
from sqlmodel import Session, select

from app.models import TeamAgent, Agent, Run, Message, RunMetric, TemplateUsage, Attachment
from app.services.runtime.loop import runtime_loop
from .state import RunState


class OrchestrationEngine:
    def __init__(self):
        pass

    async def execute(self, session: Session, run: Run, prompt: str, reflection: bool = False) -> RunState:
        links = list(session.exec(select(TeamAgent).where(TeamAgent.team_id == run.team_id).order_by(TeamAgent.position)))
        agents = [session.get(Agent, link.agent_id) for link in links if session.get(Agent, link.agent_id)]
        attachments = list(session.exec(select(Attachment).where(Attachment.run_id == run.id)))
        state = RunState(run_id=run.id, prompt=prompt, mode=run.mode, max_turns=run.max_turns, max_seconds=run.max_seconds, token_budget=run.token_budget, reflection=reflection)
        state.add('user', prompt)
        await self._dispatch(session, state, agents, run.consensus_threshold, [a.path for a in attachments if a.mime.startswith('image/')])
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
        session.commit()
        return state

    async def _dispatch(self, session: Session, state: RunState, agents: list[Agent], consensus_threshold: int, image_paths: list[str]):
        started = datetime.utcnow()
        agreements = 0
        for i, a in enumerate(agents[: state.max_turns]):
            if (datetime.utcnow() - started).total_seconds() > state.max_seconds:
                state.add('system', 'Timeout reached')
                break
            prompt = state.prompt if i == 0 else state.messages[-1]['content']
            rt = await runtime_loop.run_agent(
                session=session,
                run_id=state.run_id,
                agent=a,
                prompt=prompt,
                image_paths=image_paths,
            )
            reply = rt.final_text
            used_tools = rt.tool_calls_count
            in_toks = max(1, len(prompt) // 4)
            out_toks = max(1, len(reply) // 4)
            session.add(RunMetric(run_id=state.run_id, agent_id=a.id or 0, tokens_in=in_toks, tokens_out=out_toks, seconds=0.0, tool_calls=used_tools))
            if sum((m.get('meta', {}).get('tokens_out', 0) for m in state.messages)) + out_toks > state.token_budget:
                state.add('system', 'Max cost guard reached; run paused')
                break
            if state.repeated(reply):
                state.add('system', 'Loop detected; aborting')
                break
            if 'agree' in reply.lower() or 'consensus' in reply.lower():
                agreements += 1
            state.add('assistant', reply, a.id, meta={'model_used': rt.model_used, 'tokens_out': out_toks, 'tool_calls': used_tools, 'stop_reason': rt.stop_reason, 'warnings': rt.warnings, 'worker_used': rt.worker_used})
            if state.reflection:
                state.add('system', f'Reflection {a.name}: quality=0.8 uncertainty=0.2', a.id)

        if state.mode == 'debate' and agreements < consensus_threshold:
            state.add('system', f'Consensus threshold not met ({agreements}/{consensus_threshold}); awaiting more critique')

        session.commit()
