from __future__ import annotations

from sqlmodel import Session

from app.core.config import settings
from app.models import ModelCapability, WorkerJob

from .capsules import ingest_text_as_capsules
from .worker_queue import worker_queue


def choose_model_for_role(session: Session, role: str, has_images: bool = False) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if not settings.agentora_enable_model_role_routing:
        return settings.agentora_chat_model, warnings

    model = settings.agentora_chat_model
    if role == 'tool_planning':
        model = settings.agentora_tool_model
    elif role == 'embedding':
        model = settings.agentora_embed_model
    elif role == 'vision':
        model = settings.agentora_vision_model or settings.agentora_vision_model_fallback
    elif role == 'extraction':
        model = settings.agentora_extraction_model or settings.agentora_chat_model

    if has_images and role in {'chat', 'tool_planning'}:
        cap = session.get(ModelCapability, model)
        if cap and not cap.can_vision:
            fallback = settings.agentora_vision_model or settings.agentora_vision_model_fallback
            if fallback:
                warnings.append(f'model {model} lacks vision; rerouted to {fallback}')
                model = fallback
            else:
                warnings.append(f'model {model} lacks vision and no vision fallback configured')
    return model, warnings


async def route_capsule_ingest(session: Session, run_id: int, text: str, source: str, attachment_id: int | None = None) -> dict:
    inserted = await ingest_text_as_capsules(session=session, run_id=run_id, text=text, source=source, attachment_id=attachment_id)
    return {'ok': True, 'capsules_created': inserted}


def route_worker_job(session: Session, job_type: str, payload: dict, priority: int = 5) -> WorkerJob:
    return worker_queue.dispatch(session=session, job_type=job_type, payload=payload, priority=priority)
