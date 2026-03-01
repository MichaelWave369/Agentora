from __future__ import annotations

import json
from datetime import datetime

from pydantic import ValidationError
from sqlmodel import Session

from app.core.config import settings
from app.models import ToolCall
from app.services.ollama_client import OllamaClient
from app.services.tools.registry import registry

from .capsules import search_capsules
from .router import choose_model_for_role, route_worker_job
from .schemas import RuntimeAction, RuntimeResult
from .trace import add_trace


WORKER_TOOL_TYPES = {'python_exec': 'python_exec'}


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
    ) -> RuntimeResult:
        max_steps = min(max_steps or settings.agentora_max_tool_steps, settings.agentora_max_tool_steps)
        observations: list[str] = []
        warnings: list[str] = []
        models_used: list[str] = []
        tool_calls = 0
        worker_used = False
        stop_reason = 'max_steps'
        final_text = ''
        no_progress_ticks = 0
        prev_observations_len = 0

        allowed = []
        try:
            allowed = json.loads(agent.tools_json or '[]')
        except Exception:
            warnings.append('invalid_agent_tools_json')

        for step in range(max_steps):
            subgoal = observations[-1] if observations else prompt
            memory = await search_capsules(
                session,
                query=subgoal,
                run_id=run_id,
                top_k=settings.agentora_capsule_top_k,
            )
            add_trace(session, run_id, 'memory_layer_query', {'step': step, 'subgoal': subgoal, 'hits': memory[:4], 'layers': sorted({m.get('layer', 'unknown') for m in memory})}, agent_id=agent.id or 0)
            add_trace(session, run_id, 'context_admission', {'step': step, 'admitted': memory[: settings.agentora_max_active_contexts]}, agent_id=agent.id or 0)
            memory_text = '\n'.join([f"[{i+1}] {m['text']}" for i, m in enumerate(memory)])
            planning_model, route_warnings = choose_model_for_role(session, role='tool_planning', has_images=bool(image_paths))
            warnings.extend(route_warnings)
            models_used.append(planning_model)

            runtime_prompt = (
                f"Agent role: {agent.role}\n"
                f"User task: {prompt}\n"
                f"Current subgoal: {subgoal}\n"
                f"Observations so far:\n{chr(10).join(observations[-8:])}\n"
                f"Memory context:\n{memory_text}\n"
                "Return structured action JSON that conforms to schema."
            )

            try:
                action_data = await self.client.chat_structured(
                    model=planning_model,
                    system=agent.system_prompt,
                    prompt=runtime_prompt,
                    schema=RuntimeAction.model_json_schema(),
                )
                action = RuntimeAction.model_validate(action_data)
                add_trace(session, run_id, 'action_payload', {'step': step, 'payload': action.model_dump()}, agent_id=agent.id or 0)
            except ValidationError as exc:
                stop_reason = 'invalid_action_payload'
                warnings.append(f'invalid_action_payload:{exc.errors()[0]["type"] if exc.errors() else "unknown"}')
                add_trace(session, run_id, 'warning', {'step': step, 'message': 'invalid action payload', 'error': str(exc)}, agent_id=agent.id or 0)
                final_text = final_text or 'Runtime received an invalid planner payload and safely stopped.'
                break
            except Exception as exc:
                stop_reason = 'invalid_action_payload'
                warnings.append(f'action_planning_error:{exc}')
                add_trace(session, run_id, 'warning', {'step': step, 'message': 'planner call failed', 'error': str(exc)}, agent_id=agent.id or 0)
                final_text = final_text or 'Planner unavailable; returning safe degraded response.'
                break

            for q in action.memory_queries:
                mq = await search_capsules(session, q, run_id=run_id, top_k=2)
                if mq:
                    observations.append(f"memory[{q}]: {mq[0]['text'][:280]}")

            for tc in action.tool_calls:
                add_trace(session, run_id, 'tool_call', {'step': step, 'tool': tc.name, 'args': tc.args}, agent_id=agent.id or 0)
                try:
                    if tc.name in WORKER_TOOL_TYPES:
                        job = route_worker_job(session, WORKER_TOOL_TYPES[tc.name], {'args': tc.args, 'run_id': run_id}, priority=3)
                        worker_used = worker_used or not job.used_fallback_local
                        result = {'ok': job.status == 'done', 'job_id': job.id, 'status': job.status, 'fallback_local': job.used_fallback_local}
                        if job.status == 'fallback_local':
                            add_trace(session, run_id, 'worker_fallback', {'step': step, 'job_id': job.id, 'reason': job.error or 'worker_failed'}, agent_id=agent.id or 0)
                        else:
                            add_trace(session, run_id, 'worker_dispatch', {'step': step, 'job_id': job.id, 'status': job.status}, agent_id=agent.id or 0)
                        if job.error == 'worker_timeout':
                            stop_reason = 'worker_timeout'
                    else:
                        result = registry.call(tc.name, allowed=allowed, run_id=run_id, session=session, **tc.args)
                    session.add(
                        ToolCall(
                            run_id=run_id,
                            agent_id=agent.id or 0,
                            tool_name=tc.name,
                            args_json=json.dumps(tc.args),
                            result_json=json.dumps(result),
                            approved=bool(result.get('ok', False)),
                        )
                    )
                    tool_calls += 1
                    observations.append(f"tool[{tc.name}] => {json.dumps(result)[:350]}")
                    add_trace(session, run_id, 'tool_result', {'step': step, 'tool': tc.name, 'result': result}, agent_id=agent.id or 0)
                    if not result.get('ok', True) and stop_reason == 'max_steps':
                        warnings.append(f'tool_failed:{tc.name}')
                except Exception as exc:
                    stop_reason = 'tool_error'
                    warnings.append(f'tool_exception:{tc.name}:{exc}')
                    add_trace(session, run_id, 'warning', {'step': step, 'message': f'tool {tc.name} crashed', 'error': str(exc)}, agent_id=agent.id or 0)
                    observations.append(f'tool[{tc.name}] crashed')
                    break

            if action.final:
                final_text = action.final
            if action.handoff:
                final_text = f"{final_text}\n\nHandoff: {action.handoff}".strip()
            if action.done:
                stop_reason = 'completed' if stop_reason == 'max_steps' else stop_reason
                break

            if len(observations) == prev_observations_len and not action.final and not action.tool_calls and not action.memory_queries:
                no_progress_ticks += 1
            else:
                no_progress_ticks = 0
            prev_observations_len = len(observations)
            if no_progress_ticks >= 2:
                stop_reason = 'no_progress'
                warnings.append('loop_no_progress')
                break

        if not final_text:
            final_text = 'No final answer generated.'
            if stop_reason == 'max_steps':
                warnings.append('max_steps_reached_without_final')

        add_trace(session, run_id, 'final_answer', {'final_text': final_text[:1000], 'stop_reason': stop_reason, 'warnings': warnings, 'models_used': models_used}, agent_id=agent.id or 0)
        return RuntimeResult(
            final_text=final_text,
            tool_calls_count=tool_calls,
            stop_reason=stop_reason,
            warnings=warnings,
            worker_used=worker_used,
            model_used=models_used,
        )


runtime_loop = RuntimeLoop()
