"""Opt-in local PhiAtelier endpoints. No filesystem writes, renders or publishing."""
from __future__ import annotations

import os
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.ollama_client import OllamaClient
from phi_atelier import ArtBrief, compile_brief
from phi_atelier.director import AUDIT_CHECKLIST, direction_receipt, prepare_direction

router = APIRouter(prefix="/api/atelier", tags=["atelier"])


class ArtBriefInput(BaseModel):
    concept: str = Field(min_length=1, max_length=1000)
    symbolism: str = Field(default="", max_length=1000)
    restrictions: str = Field(default="", max_length=1000)
    orientation: Literal["landscape", "portrait", "square"] = "landscape"
    rendering: Literal["photoreal", "fine-art", "concept-art"] = "photoreal"
    influences: dict[str, int] = Field(
        default_factory=lambda: {"escher": 1, "dali": 1, "picasso": 1}
    )


class DirectorInput(BaseModel):
    brief: ArtBriefInput
    direction: Literal["monumental", "intimate", "recursive"] = "recursive"
    confirm_model_call: bool = False


def _brief(payload: ArtBriefInput) -> ArtBrief:
    return ArtBrief(**payload.model_dump())


def _check_origin(request: Request) -> None:
    """Prevent arbitrary cross-site browser pages from calling local Ollama."""
    origin = request.headers.get("origin")
    if origin is None:
        return  # command-line/local callers may omit Origin
    try:
        parsed = urlsplit(origin)
    except ValueError:
        raise HTTPException(status_code=403, detail="invalid request origin")
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "localhost", "127.0.0.1", "::1"
    ) or parsed.username or parsed.password:
        raise HTTPException(status_code=403, detail="local origin required")


@router.post("/preview")
def preview(payload: ArtBriefInput):
    try:
        result = compile_brief(_brief(payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True, "bundle": result,
        "audit_checklist": list(AUDIT_CHECKLIST),
        "model_call": False, "render_status": "not_rendered",
    }


@router.post("/direct")
async def direct(payload: DirectorInput, request: Request):
    """Run a single, explicitly requested Ollama structured-text call.

    Disabled unless the local operator enables AGENTORA_ATELIER_MODEL_ENABLED.
    Returns an unreviewed text-only design. It cannot invoke image generation.
    """
    _check_origin(request)
    if not payload.confirm_model_call:
        raise HTTPException(status_code=403, detail="explicit model-call confirmation required")
    if os.environ.get("AGENTORA_ATELIER_MODEL_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="PhiAtelier local model calls disabled")
    if settings.agentora_use_mock_ollama:
        raise HTTPException(status_code=503, detail="real local model required; mock mode cannot direct")
    try:
        prepared = prepare_direction(_brief(payload.brief), payload.direction)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    model = settings.agentora_chat_model
    try:
        raw = await OllamaClient().chat_structured(
            model=model, system=prepared["model_system"],
            prompt=prepared["model_prompt"], schema=prepared["model_schema"],
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="local model unavailable") from exc
    try:
        receipt = direction_receipt(prepared, raw, model_name=model)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"model proposal rejected: {exc}") from exc
    return {"ok": True, "receipt": receipt}
