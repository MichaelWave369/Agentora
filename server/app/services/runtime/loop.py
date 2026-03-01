from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session

from app.core.config import settings
from app.models import ToolCall
from app.services.ollama_client import OllamaClient
from app.services.tools.registry import registry

from .capsules import search_capsules
from .schemas import RuntimeAction


class RuntimeLoop:
    def __init__(self):
        self.client = OllamaClient()

    async def run_agent(
        self,
        session: Session,
        run_id: int,
        agent,
        prompt: str,
        image_paths: list[str] | None = None,
        max_steps: int | None = None,
    ) -> tuple[str, int, float, str]:
        max_steps = max_steps or settings.agentora_max_tool_steps
        observations: list[str] = []
        tool_calls = 0
        started = datetime.utcnow()
        final_text = ''
        model_used = settings.agentora_chat_model

        allowed = []
        try:
            allowed = json.loads(agent.tools_json or '[]')
        except Exception:
            allowed = []

        for step in range(max_steps):
            memory = await search_capsules(session, query=prompt, run_id=run_id, top_k=settings.agentora_capsule_top_k)
            memory_text = '\n'.join([f"[{i+1}] {m['text']}" for i, m in enumerate(memory)])
            runtime_prompt = (
                f"Agent role: {agent.role}\n"
                f"User task: {prompt}\n"
                f"Observations so far:\n{chr(10).join(observations[-6:])}\n"
                f"Memory context:\n{memory_text}\n"
                "Return structured action JSON."
            )
            action_data = await self.client.chat_structured(
                model=settings.agentora_chat_model,
                system=agent.system_prompt,
                prompt=runtime_prompt,
                schema=RuntimeAction.model_json_schema(),
            )
            action = RuntimeAction.model_validate(action_data)

            for q in action.memory_queries:
                mq = await search_capsules(session, q, run_id=run_id, top_k=2)
                if mq:
                    observations.append(f"memory[{q}]: {mq[0]['text'][:300]}")

            for tc in action.tool_calls:
                result = registry.call(tc.name, allowed=allowed, run_id=run_id, session=session, **tc.args)
                session.add(
                    ToolCall(
                        run_id=run_id,
                        agent_id=agent.id or 0,
                        tool_name=tc.name,
                        args_json=json.dumps(tc.args),
                        result_json=json.dumps(result),
                        approved=True,
                    )
                )
                tool_calls += 1
                observations.append(f"tool[{tc.name}] => {json.dumps(result)[:500]}")

            if action.final:
                final_text = action.final
            if action.handoff:
                final_text = f"{final_text}\n\nHandoff: {action.handoff}".strip()
            if action.done:
                break

            if not action.tool_calls and not action.memory_queries and action.final:
                break

        elapsed = (datetime.utcnow() - started).total_seconds()
        if not final_text:
            final_text = 'No final answer generated.'
        return final_text, tool_calls, elapsed, model_used


runtime_loop = RuntimeLoop()
