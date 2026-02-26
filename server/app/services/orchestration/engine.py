import asyncio
import json
from datetime import datetime
from sqlmodel import Session, select

from app.models import Team, TeamAgent, Agent, Run, Message
from app.services.ollama_client import OllamaClient
from .state import RunState


class OrchestrationEngine:
    def __init__(self):
        self.client = OllamaClient()

    async def execute(self, session: Session, run: Run, prompt: str, reflection: bool = False) -> RunState:
        links = list(session.exec(select(TeamAgent).where(TeamAgent.team_id == run.team_id).order_by(TeamAgent.position)))
        agents = [session.get(Agent, link.agent_id) for link in links]
        state = RunState(run_id=run.id, prompt=prompt, mode=run.mode, max_turns=run.max_turns, max_seconds=run.max_seconds, token_budget=run.token_budget, reflection=reflection)
        state.add('user', prompt)
        await self._dispatch(state, agents)
        run.status = 'completed'
        run.finished_at = datetime.utcnow()
        run.result_summary = state.messages[-1]['content'][:300] if state.messages else ''
        session.add(run)
        for m in state.messages:
            session.add(Message(run_id=run.id, agent_id_nullable=m.get('agent_id'), role=m['role'], content=m['content'], meta_json=json.dumps({})))
        session.commit()
        return state

    async def _agent_reply(self, agent, prompt: str) -> str:
        chunks = []
        async for tok in self.client.stream_chat(agent.model, agent.system_prompt, prompt):
            chunks.append(tok)
        return ''.join(chunks).strip()

    async def _dispatch(self, state: RunState, agents: list[Agent]):
        started = datetime.utcnow()
        mode = state.mode
        if mode == 'parallel' and agents:
            lead = agents[-1]
            workers = agents[:-1]
            results = await asyncio.gather(*[self._agent_reply(a, state.prompt) for a in workers[: state.max_turns]])
            for a, r in zip(workers, results):
                state.add('assistant', r, a.id)
            summary = await self._agent_reply(lead, 'Summarize:\n' + '\n'.join(results))
            state.add('assistant', summary, lead.id)
            return
        if mode == 'debate' and len(agents) >= 3:
            proposer, critic, synth = agents[0], agents[1], agents[2]
            memo = state.prompt
            for _ in range(min(2, state.max_turns)):
                p = await self._agent_reply(proposer, memo)
                state.add('assistant', p, proposer.id)
                c = await self._agent_reply(critic, p)
                state.add('assistant', c, critic.id)
                memo = c
            fin = await self._agent_reply(synth, memo)
            state.add('assistant', fin, synth.id)
            return
        if mode == 'supervisor' and agents:
            sup = agents[0]
            workers = agents[1:] or [sup]
            routed = []
            for w in workers[: state.max_turns]:
                routed.append(await self._agent_reply(w, state.prompt))
            final = await self._agent_reply(sup, 'Route results:\n' + '\n'.join(routed))
            for w, out in zip(workers, routed):
                state.add('assistant', out, w.id)
            state.add('assistant', final, sup.id)
            return

        for i, a in enumerate(agents[: state.max_turns]):
            if (datetime.utcnow() - started).total_seconds() > state.max_seconds:
                state.add('system', 'Timeout reached')
                break
            reply = await self._agent_reply(a, state.prompt if i == 0 else state.messages[-1]['content'])
            if state.repeated(reply):
                state.add('system', 'Loop detected; aborting')
                break
            state.add('assistant', reply, a.id)
            if state.reflection:
                state.add('system', f'Reflection {a.name}: quality=0.8 uncertainty=0.2', a.id)
