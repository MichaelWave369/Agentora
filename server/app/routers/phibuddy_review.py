"""Separately enabled R04-B review endpoint."""
import hmac
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.services.phibuddy_bridge import decode
from app.services.phibuddy_review import MAX_REQUEST, provider_review, validate_request

router = APIRouter(prefix="/api/phibuddy", tags=["phibuddy-review"])


@router.post("/advisory/review")
async def review(request: Request):
    if (os.environ.get("AGENTORA_PHIBUDDY_BRIDGE_ENABLED") != "1"
            or os.environ.get("AGENTORA_PHIBUDDY_REVIEW_ENABLED") != "1"):
        raise HTTPException(404, "Review disabled")
    if (request.client is None or request.client.host != "127.0.0.1"
            or request.headers.get("host") != "127.0.0.1:8088"
            or "origin" in request.headers):
        raise HTTPException(403, "Direct loopback CLI required")
    key = os.environ.get("AGENTORA_PHIBUDDY_BRIDGE_KEY", "")
    supplied = request.headers.get("x-phibuddy-bridge-key", "")
    if (not re.fullmatch(r"[0-9a-f]{64}", key)
            or not re.fullmatch(r"[0-9a-f]{64}", supplied)
            or not hmac.compare_digest(key, supplied)):
        raise HTTPException(403, "Operator key required")
    if settings.agentora_use_mock_ollama or settings.ollama_url.rstrip("/") != "http://127.0.0.1:11434":
        raise HTTPException(503, "Explicit real local Ollama configuration required")
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "JSON required")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REQUEST:
            raise HTTPException(413, "Request too large")
        raw.extend(chunk)
    try:
        payload = decode(bytes(raw))
        validate_request(payload)
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid review request") from None
    allowed = {v.strip() for v in os.environ.get("AGENTORA_PHIBUDDY_REVIEW_MODELS", "").split(",") if v.strip()}
    if payload["model"] not in allowed:
        raise HTTPException(403, "Model not allowlisted")
    try:
        return await provider_review(payload)
    except (ValueError, OSError, httpx.HTTPError, RecursionError, TimeoutError):
        raise HTTPException(503, "Local review unavailable; no confirmed receipt") from None
