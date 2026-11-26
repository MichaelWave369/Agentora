"""Opt-in, stateless PhiBuddy preview endpoint."""
import hmac
import os
import re

from fastapi import APIRouter, HTTPException, Request

from app.services.phibuddy_bridge import MAX_PACKET, decode, validate

router = APIRouter(prefix="/api/phibuddy", tags=["phibuddy-bridge"])


@router.post("/advisory/preview")
async def preview(request: Request):
    if os.environ.get("AGENTORA_PHIBUDDY_BRIDGE_ENABLED") != "1":
        raise HTTPException(404, "Bridge disabled")
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
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "JSON required")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_PACKET:
            raise HTTPException(413, "Packet too large")
        raw.extend(chunk)
    try:
        return validate(decode(bytes(raw)))
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid advisory packet") from None
