"""PhiAtelier Rung 6: no-cloud, one-shot vision critique contracts."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import atelier
from phi_atelier.comfy_bridge import RenderBridgeError
from phi_atelier.vision import (
    CONTENT_FIELDS, MAX_RESPONSE_BYTES, LocalVisionCritic,
    VisionUnavailable, SCHEMA, validate_observation,
)

JOB = str(uuid4())
PNG = b"\x89PNG\r\n\x1a\n" + b"art-image-fixture-bytes"
KEY = "private-local-secret-at-least-24-chars"
PROMPT = "A glass city with recursive bridges and one strong foreground silhouette"


def observation():
    return {
        "visible_subjects": "An architectural city scene with glass bridges and a prominent foreground silhouette.",
        "composition_observations": "A leading path connects the foreground figure with the center of interest and repeating arches.",
        "lighting_color_observations": "Cool ambient light contrasts with warm windows, but the middle range is slightly compressed.",
        "prompt_alignment": "The visible geometry seems to address the requested recursive bridges, although the focal human could be clearer.",
        "possible_issues": "The foreground human silhouette blends into nearby structures and may lose readability at smaller sizes.",
        "specific_suggestions": "Brighten the human silhouette, reduce secondary arch complexity, and separate the background planes by contrast.",
        "uncertainties": "I cannot verify the original intention, actual rights, pixel-level rendering artifacts, or whether the scene is novel.",
    }


def fake_ollama(reply=None, status=200):
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={
            "message": {"content": json.dumps(observation() if reply is None else reply)},
        })
    return httpx.MockTransport(handle), calls


def test_valid_local_vision_receipt_is_unverified_and_never_renders(monkeypatch):
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_MODEL", "llama3.2-vision")
    monkeypatch.setenv("AGENTORA_ATELIER_OLLAMA_PORT", "11434")
    transport, calls = fake_ollama()
    service = LocalVisionCritic(transport=transport)
    report = asyncio.run(service.review(
        job_id=JOB, image=PNG, mime="image/png", intended_prompt=PROMPT,
    ))
    assert len(calls) == 1
    sent = json.loads(calls[0].content)
    assert calls[0].url.host == "127.0.0.1"
    assert calls[0].url.path == "/api/chat"
    assert sent["stream"] is False and sent["format"] == SCHEMA
    assert sent["messages"][1]["images"] and len(sent["messages"][1]["images"]) == 1
    assert report["job_id"] == JOB
    assert report["image_sha256"].startswith("sha256:")
    assert report["review_status"] == "human_review_required"
    assert report["origin"] == "local_vision_model_unverified"
    assert report["new_render_queued"] is False
    assert report["model_call_count"] == 1
    assert report["visual_quality_verified"] is False


def test_response_is_strictly_bounded_and_fields_reject_extras():
    assert validate_observation(observation()) == observation()
    with pytest.raises(VisionUnavailable, match="unexpected fields"):
        validate_observation({**observation(), "shell_command": "do not run"})
    with pytest.raises(VisionUnavailable, match="invalid vision response"):
        validate_observation({**observation(), "visible_subjects": ""})
    with pytest.raises(VisionUnavailable):
        validate_observation({**observation(), "specific_suggestions": "x" * 2000})


@pytest.mark.parametrize("mime, data", [
    ("image/png", b"not a real png image"),
    ("application/octet-stream", PNG),
    ("image/jpeg", PNG),
    ("image/png", b"short"),
])
def test_invalid_images_never_contact_local_model(monkeypatch, mime, data):
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_MODEL", "llama3.2-vision")
    transport, calls = fake_ollama()
    service = LocalVisionCritic(transport=transport)
    with pytest.raises(VisionUnavailable):
        asyncio.run(service.review(job_id=JOB, image=data, mime=mime, intended_prompt=PROMPT))
    assert calls == []


def test_missing_model_and_concurrent_review_fail_closed(monkeypatch):
    monkeypatch.delenv("AGENTORA_ATELIER_VISION_MODEL", raising=False)
    transport, calls = fake_ollama()
    service = LocalVisionCritic(transport=transport)
    with pytest.raises(VisionUnavailable, match="configured"):
        asyncio.run(service.review(job_id=JOB, image=PNG, mime="image/png", intended_prompt=PROMPT))
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_MODEL", "llama3.2-vision")
    service._active.acquire()
    try:
        with pytest.raises(VisionUnavailable, match="already running"):
            asyncio.run(service.review(job_id=JOB, image=PNG, mime="image/png", intended_prompt=PROMPT))
    finally:
        service._active.release()
    assert calls == []


def test_ollama_error_or_malformed_reply_not_accepted(monkeypatch):
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_MODEL", "llama3.2-vision")
    service = LocalVisionCritic(transport=fake_ollama(status=404)[0])
    with pytest.raises(VisionUnavailable, match="rejected"):
        asyncio.run(service.review(job_id=JOB, image=PNG, mime="image/png", intended_prompt=PROMPT))
    service = LocalVisionCritic(transport=fake_ollama(reply={"unknown": "field"})[0])
    with pytest.raises(VisionUnavailable, match="unexpected fields"):
        asyncio.run(service.review(job_id=JOB, image=PNG, mime="image/png", intended_prompt=PROMPT))


class LocalImages:
    def __init__(self):
        self.lookups = 0
        self.images = 0

    def get_job(self, job_id):
        self.lookups += 1
        if job_id != JOB:
            raise RenderBridgeError("render job not found in this Agentora process", 404)
        return {"prompt_id": JOB, "positive_prompt": PROMPT, "image_ready": True}

    async def image(self, job_id):
        self.images += 1
        if job_id != JOB:
            raise RenderBridgeError("unknown render job", 404)
        return PNG, "image/png"


def client_setup(monkeypatch):
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_KEY", KEY)
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_MODEL", "llama3.2-vision")
    image_source = LocalImages()
    transport, calls = fake_ollama()
    monkeypatch.setattr(atelier, "comfy_bridge", image_source)
    monkeypatch.setattr(atelier, "vision_critic", LocalVisionCritic(transport=transport))
    return TestClient(create_app(), base_url="http://127.0.0.1:8088"), image_source, calls


def test_api_requires_key_enable_explicit_confirmation_before_image(monkeypatch):
    client, source, calls = client_setup(monkeypatch)
    path = "/api/atelier/studio/vision/" + JOB
    no_key = client.post(path, json={"confirm_local_model_call": True})
    assert no_key.status_code == 403
    headers = {"X-Atelier-Operator-Key": KEY}
    no_consent = client.post(path, headers=headers, json={"confirm_local_model_call": False})
    assert no_consent.status_code == 403
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_ENABLED", "false")
    disabled = client.post(path, headers=headers, json={"confirm_local_model_call": True})
    assert disabled.status_code == 404
    assert source.lookups == source.images == len(calls) == 0


def test_api_uses_only_owned_completed_image_and_returns_unverified_report(monkeypatch):
    client, source, calls = client_setup(monkeypatch)
    headers = {"X-Atelier-Operator-Key": KEY}
    unknown = str(uuid4())
    denied = client.post("/api/atelier/studio/vision/" + unknown,
                         headers=headers, json={"confirm_local_model_call": True})
    assert denied.status_code == 404
    assert source.images == 0 and len(calls) == 0
    allowed = client.post("/api/atelier/studio/vision/" + JOB,
                          headers=headers, json={"confirm_local_model_call": True})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["report"]["new_render_queued"] is False
    assert source.images == 1 and len(calls) == 1


def test_cross_site_request_rejected_even_with_operator_key(monkeypatch):
    client, source, calls = client_setup(monkeypatch)
    res = client.post("/api/atelier/studio/vision/" + JOB,
                      headers={"X-Atelier-Operator-Key": KEY, "Origin": "https://outside.example"},
                      json={"confirm_local_model_call": True})
    assert res.status_code == 403
    assert source.images == 0 and not calls
