"""Opt-in local PhiAtelier endpoints. No filesystem writes, renders or publishing."""
from __future__ import annotations

import os
import hmac
from urllib.parse import urlsplit
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.ollama_client import OllamaClient
from phi_atelier import ArtBrief, compile_brief
from phi_atelier.director import AUDIT_CHECKLIST, direction_receipt, prepare_direction
from phi_atelier.knowledge import KnowledgeUnavailable, load_approved_visual_grammar
from phi_atelier.render_plan import build_render_plan
from phi_atelier.comfy_bridge import ComfyRenderBridge, RenderBridgeError
from phi_atelier.studio import prepare_revision
from phi_atelier.vision import LocalVisionCritic, VisionUnavailable
from phi_atelier.memory import ReviewMemory, MemoryError as FeedbackMemoryError

router = APIRouter(prefix="/api/atelier", tags=["atelier"])
comfy_bridge = ComfyRenderBridge()
vision_critic = LocalVisionCritic()
review_memory = ReviewMemory(database=os.environ.get("AGENTORA_ATELIER_MEMORY_DB") or None)


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


class RenderPlanInput(BaseModel):
    positive_prompt: str = Field(min_length=1, max_length=3000)
    negative_prompt: str = Field(default="", max_length=850)
    aspect_ratio: Literal["16:9", "3:4", "1:1"] = "16:9"
    seed: int = Field(default=369, ge=0, le=4294967295)
    steps: int = Field(default=24, ge=8, le=40)
    cfg: float = Field(default=7.0, ge=1.0, le=12.0)


class RenderSubmitInput(RenderPlanInput):
    workflow_digest: str = Field(min_length=71, max_length=71)
    approve_gpu_render: bool = False


class CancelRenderInput(BaseModel):
    confirm_cancel: bool = False

class HumanDecisionInput(BaseModel):
    review_digest: str = Field(min_length=71, max_length=71)
    decision: Literal["accepted", "rejected", "revised"]
    human_reason: str = Field(min_length=8, max_length=500)
    edited_guidance: str = Field(default="", max_length=700)
    human_confirm: bool = False


class VisionReviewInput(BaseModel):
    confirm_local_model_call: bool = False


class HumanReviewInput(BaseModel):
    original_prompt: str = Field(min_length=1, max_length=3000)
    scores: dict[str, int]
    observations: str = Field(default="", max_length=1000)
    requested_changes: str = Field(min_length=1, max_length=700)
    parent_job_id: str | None = None


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


def _require_render_operator(request: Request) -> None:
    """Refuse remote hosts, cross-site calls, missing key, or disabled renderer."""
    _check_origin(request)
    if request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="render control is loopback-only")
    if os.environ.get("AGENTORA_ATELIER_RENDER_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="local rendering disabled")
    operator_key = os.environ.get("AGENTORA_ATELIER_RENDER_KEY", "")
    supplied = request.headers.get("x-atelier-operator-key", "")
    if (len(operator_key) < 24 or len(supplied) > 256
            or not operator_key.isascii() or not supplied.isascii()
            or not hmac.compare_digest(supplied, operator_key)):
        raise HTTPException(status_code=403, detail="operator key required")


def _render_draft(payload: RenderPlanInput) -> dict:
    checkpoint = os.environ.get("AGENTORA_ATELIER_CHECKPOINT", "")
    if not checkpoint:
        raise HTTPException(status_code=503, detail="operator checkpoint not configured")
    try:
        return build_render_plan(
            positive_prompt=payload.positive_prompt,
            negative_prompt=payload.negative_prompt,
            checkpoint=checkpoint,
            aspect_ratio=payload.aspect_ratio,
            seed=payload.seed, steps=payload.steps, cfg=payload.cfg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    reference = None
    if os.environ.get("AGENTORA_ATELIER_KNOWLEDGE_ENABLED", "").lower() == "true":
        pack_path = os.environ.get("AGENTORA_ATELIER_PACK_PATH", "")
        ledger_path = os.environ.get("AGENTORA_ATELIER_REVIEWS_DB", "")
        if not pack_path or not ledger_path:
            raise HTTPException(status_code=503, detail="reviewed knowledge paths not configured")
        try:
            reference = load_approved_visual_grammar(pack_path, ledger_path)
        except (KnowledgeUnavailable, OSError) as exc:
            raise HTTPException(status_code=503, detail=f"reviewed knowledge unavailable: {exc}") from exc
    try:
        prepared = prepare_direction(
            _brief(payload.brief), payload.direction, reviewed_reference=reference,
        )
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


@router.post("/render-plan")
def render_plan(payload: RenderPlanInput, request: Request):
    """Build one ComfyUI API-format workflow without any network or GPU call."""
    _check_origin(request)
    return {"ok": True, "plan": _render_draft(payload)}


@router.post("/render/submit")
async def submit_render(payload: RenderSubmitInput, request: Request):
    """Each job needs an explicit digest-matched approval and operator secret."""
    _require_render_operator(request)
    if payload.approve_gpu_render is not True:
        raise HTTPException(status_code=403, detail="explicit GPU-render approval required")
    draft = _render_draft(payload)
    if not hmac.compare_digest(payload.workflow_digest, draft["workflow_digest"]):
        raise HTTPException(status_code=409, detail="render plan changed since preview")
    try:
        record = await comfy_bridge.submit(draft)
    except RenderBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"ok": True, "job": record}


@router.get("/render/{prompt_id}/status")
async def render_status(prompt_id: str, request: Request):
    _require_render_operator(request)
    try:
        record = await comfy_bridge.status(prompt_id)
    except RenderBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"ok": True, "job": record}


@router.get("/render/{prompt_id}/image")
async def render_image(prompt_id: str, request: Request):
    _require_render_operator(request)
    try:
        pixels, mime = await comfy_bridge.image(prompt_id)
    except RenderBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return Response(content=pixels, media_type=mime, headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'inline; filename="PhiAtelier-result"',
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/render/{prompt_id}/cancel")
async def cancel_render(prompt_id: str, payload: CancelRenderInput, request: Request):
    _require_render_operator(request)
    if not payload.confirm_cancel:
        raise HTTPException(status_code=403, detail="explicit cancellation confirmation required")
    try:
        record = await comfy_bridge.cancel(prompt_id)
    except RenderBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"ok": True, "job": record}


@router.get("/studio/jobs")
def studio_jobs(request: Request):
    """List only the render IDs this Agentora process submitted."""
    _require_render_operator(request)
    return {
        "ok": True,
        "items": comfy_bridge.list_jobs(),
        "scope": "process_local",
        "persistent": False,
    }


@router.post("/studio/revision")
def studio_revision(payload: HumanReviewInput, request: Request):
    """Bounded human-only revision receipt, no model or rendering call."""
    _check_origin(request)
    try:
        revision = prepare_revision(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "revision": revision}

@router.post("/studio/vision/{prompt_id}")
async def studio_vision_review(prompt_id: str, payload: VisionReviewInput, request: Request):
    """Explicit one-shot visual critique of one completed, owned ComfyUI image."""
    _require_render_operator(request)
    if os.environ.get("AGENTORA_ATELIER_VISION_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="local visual analysis disabled")
    if not payload.confirm_local_model_call:
        raise HTTPException(status_code=403, detail="explicit local vision-model approval required")
    try:
        source = comfy_bridge.get_job(prompt_id)
        pixels, mime = await comfy_bridge.image(prompt_id)
        report = await vision_critic.review(
            job_id=prompt_id, image=pixels, mime=mime,
            intended_prompt=source["positive_prompt"],
        )
    except RenderBridgeError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except VisionUnavailable as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    if os.environ.get("AGENTORA_ATELIER_MEMORY_ENABLED", "").lower() == "true":
        try:
            report["review_digest"] = review_memory.stage(
                report, original_prompt=source["positive_prompt"]
            )
        except FeedbackMemoryError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"ok": True, "report": report}


def _require_memory_operator(request: Request) -> None:
    _require_render_operator(request)
    if os.environ.get("AGENTORA_ATELIER_MEMORY_ENABLED", "").lower() != "true":
        raise HTTPException(status_code=404, detail="local artist feedback memory disabled")


@router.post("/studio/memory/decision")
def studio_memory_decision(payload: HumanDecisionInput, request: Request):
    """Explicit human decision about one pinned, staged vision report."""
    _require_memory_operator(request)
    try:
        entry = review_memory.decide(**payload.model_dump())
    except FeedbackMemoryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return {"ok": True, "entry": entry}


@router.get("/studio/memory")
def studio_memory_list(request: Request):
    """Human-controlled local ledger, not background model context."""
    _require_memory_operator(request)
    try:
        return {"ok": True, "memory": review_memory.list_decisions()}
    except FeedbackMemoryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/studio/memory/context")
def studio_memory_context(request: Request):
    """Show approved-only notes for manual use; never load into a model."""
    _require_memory_operator(request)
    try:
        return {"ok": True, "context": review_memory.accepted_context()}
    except FeedbackMemoryError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
