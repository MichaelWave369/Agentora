"""PhiAtelier Rung 4 integration tests: fake ComfyUI transport, never a GPU."""
import asyncio
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import atelier
from phi_atelier.comfy_bridge import (
    ComfyRenderBridge, RenderBridgeError, MAX_IMAGE_BYTES,
)
from phi_atelier.render_plan import build_render_plan

OPERATOR_KEY = "test-operator-key-with-at-least-24-characters"
PNG = b"\x89PNG\r\n\x1a\n" + b"test-png-payload"
RENDER_PAYLOAD = {
    "positive_prompt": "An original nested city under warm dawn",
    "negative_prompt": "watermarks and accidental letters",
    "aspect_ratio": "16:9",
    "seed": 369,
    "steps": 24,
    "cfg": 7.0,
}


class FakeComfy:
    def __init__(self):
        self.calls = []
        self.models = ["art-local.safetensors"]
        self.state = "queued"
        self.last_prompt = None
        self.filename = "PhiAtelier_00001_.png"
        self.image_bytes = PNG
        self.fail_submission = False
        self.timeout_submission = False
        self.view_count = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/models/checkpoints":
            return httpx.Response(200, json=self.models)
        if path == "/prompt" and request.method == "POST":
            self.last_prompt = json.loads(request.content)
            if self.timeout_submission:
                raise httpx.ConnectError("simulated connection dropped", request=request)
            if self.fail_submission:
                return httpx.Response(400, json={"error": "simulated invalid workflow"})
            return httpx.Response(200, json={
                "prompt_id": self.last_prompt["prompt_id"], "number": 0,
            })
        if path.startswith("/history/"):
            if self.last_prompt is None:
                return httpx.Response(200, json={})
            ident = self.last_prompt["prompt_id"]
            if self.state == "completed":
                return httpx.Response(200, json={ident: {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {"9": {"images": [
                        {"filename": self.filename, "type": "output", "subfolder": ""},
                    ]}},
                }})
            if self.state == "failed":
                return httpx.Response(200, json={ident: {
                    "status": {"status_str": "error", "completed": True},
                    "outputs": {},
                }})
            return httpx.Response(200, json={})
        if path == "/queue" and request.method == "GET":
            entry = [0, self.last_prompt["prompt_id"], {}, {}] if self.last_prompt else None
            return httpx.Response(200, json={
                "queue_pending": [entry] if entry and self.state == "queued" else [],
                "queue_running": [entry] if entry and self.state == "running" else [],
            })
        if path == "/queue" and request.method == "POST":
            assert json.loads(request.content) == {
                "delete": [self.last_prompt["prompt_id"]]
            }
            self.state = "cancel_requested"
            return httpx.Response(200, json={})
        if path == "/interrupt" and request.method == "POST":
            assert json.loads(request.content) == {
                "prompt_id": self.last_prompt["prompt_id"]
            }
            self.state = "cancel_requested"
            return httpx.Response(200, json={})
        if path == "/view":
            self.view_count += 1
            assert request.url.params["filename"] == self.filename
            assert request.url.params["type"] == "output"
            assert request.url.params["subfolder"] == ""
            return httpx.Response(200, content=self.image_bytes, headers={"content-type": "image/png"})
        return httpx.Response(404, json={"error": "unknown fake route"})

    def bridge(self):
        transport = httpx.MockTransport(self.handle)

        def client_factory(port):
            assert port == 8188
            return httpx.AsyncClient(
                base_url="http://127.0.0.1:8188", transport=transport,
                follow_redirects=False, trust_env=False,
            )
        return ComfyRenderBridge(client_factory=client_factory)


def plan():
    return build_render_plan(
        **RENDER_PAYLOAD, checkpoint="art-local.safetensors",
    )


def fake_service(monkeypatch):
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_KEY", OPERATOR_KEY)
    monkeypatch.setenv("AGENTORA_ATELIER_CHECKPOINT", "art-local.safetensors")
    monkeypatch.setenv("AGENTORA_ATELIER_COMFY_PORT", "8188")
    server = FakeComfy()
    monkeypatch.setattr(atelier, "comfy_bridge", server.bridge())
    client = TestClient(create_app(), base_url="http://127.0.0.1:8088")
    headers = {"X-Atelier-Operator-Key": OPERATOR_KEY}
    return server, client, headers


def approved():
    return {
        **RENDER_PAYLOAD,
        "workflow_digest": plan()["workflow_digest"],
        "approve_gpu_render": True,
    }


def test_disabled_and_missing_operator_key_fail_before_network(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    monkeypatch.delenv("AGENTORA_ATELIER_RENDER_ENABLED")
    response = client.post("/api/atelier/render/submit", headers=headers, json=approved())
    assert response.status_code == 404
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_ENABLED", "true")
    assert client.post("/api/atelier/render/submit", json=approved()).status_code == 403
    assert not server.calls


def test_wrong_origin_and_missing_confirmation_fail_before_network(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    bad_origin = {**headers, "Origin": "https://elsewhere.example"}
    assert client.post("/api/atelier/render/submit", headers=bad_origin, json=approved()).status_code == 403
    body = approved()
    body["approve_gpu_render"] = False
    assert client.post("/api/atelier/render/submit", headers=headers, json=body).status_code == 403
    assert not server.calls


def test_stale_digest_and_missing_checkpoint_fail_before_network(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    body = approved()
    body["workflow_digest"] = "sha256:" + "0" * 64
    assert client.post("/api/atelier/render/submit", headers=headers, json=body).status_code == 409
    monkeypatch.delenv("AGENTORA_ATELIER_CHECKPOINT")
    assert client.post("/api/atelier/render/submit", headers=headers, json=approved()).status_code == 503
    assert not server.calls


def test_submit_requires_real_checkpoint_and_one_exact_graph(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    server.models = ["other.safetensors"]
    blocked = client.post("/api/atelier/render/submit", headers=headers, json=approved())
    assert blocked.status_code == 422
    assert all(path != "/prompt" for _, path in server.calls)
    server.models = ["art-local.safetensors"]
    created = client.post("/api/atelier/render/submit", headers=headers, json=approved())
    assert created.status_code == 200, created.text
    ident = created.json()["job"]["prompt_id"]
    assert str(uuid.UUID(ident)) == ident
    assert server.last_prompt["prompt"] == plan()["workflow"]
    assert server.last_prompt["prompt_id"] == ident
    assert [p for _, p in server.calls].count("/prompt") == 1
    same = client.post("/api/atelier/render/submit", headers=headers, json=approved())
    assert same.status_code == 409
    assert [p for _, p in server.calls].count("/prompt") == 1


def test_queue_running_complete_and_image_preview(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    job = client.post("/api/atelier/render/submit", headers=headers, json=approved()).json()["job"]
    uri = f"/api/atelier/render/{job['prompt_id']}"
    queued = client.get(uri + "/status", headers=headers)
    assert queued.json()["job"]["status"] == "queued"
    server.state = "running"
    running = client.get(uri + "/status", headers=headers)
    assert running.json()["job"]["status"] == "running"
    assert client.get(uri + "/image", headers=headers).status_code == 409
    server.state = "completed"
    completed = client.get(uri + "/status", headers=headers)
    assert completed.json()["job"]["status"] == "completed"
    assert completed.json()["job"]["image_ready"] is True
    image = client.get(uri + "/image", headers=headers)
    assert image.status_code == 200
    assert image.content == PNG
    assert image.headers["content-type"].startswith("image/png")
    assert image.headers["cache-control"] == "no-store"
    assert server.view_count == 1


def test_only_own_jobs_accessible(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    foreign_id = str(uuid.uuid4())
    assert client.get(f"/api/atelier/render/{foreign_id}/status", headers=headers).status_code == 404
    assert client.get(f"/api/atelier/render/{foreign_id}/image", headers=headers).status_code == 404
    assert not server.calls


def test_targeted_pending_cancellation_and_running_interrupt(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    job = client.post("/api/atelier/render/submit", headers=headers, json=approved()).json()["job"]
    uri = f"/api/atelier/render/{job['prompt_id']}/cancel"
    assert client.post(uri, headers=headers, json={"confirm_cancel": False}).status_code == 403
    answer = client.post(uri, headers=headers, json={"confirm_cancel": True})
    assert answer.status_code == 200, answer.text
    assert answer.json()["job"]["status"] == "cancellation_requested"
    assert ("POST", "/queue") in server.calls

    server2, client2, headers2 = fake_service(monkeypatch)
    server2.state = "running"
    job2 = client2.post("/api/atelier/render/submit", headers=headers2, json=approved()).json()["job"]
    uri2 = f"/api/atelier/render/{job2['prompt_id']}/cancel"
    assert client2.post(uri2, headers=headers2, json={"confirm_cancel": True}).status_code == 200
    assert ("POST", "/interrupt") in server2.calls


def test_malicious_image_filename_never_passed_to_view(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    job = client.post("/api/atelier/render/submit", headers=headers, json=approved()).json()["job"]
    server.state = "completed"
    server.filename = "../other-private-image.png"
    response = client.get(f"/api/atelier/render/{job['prompt_id']}/image", headers=headers)
    assert response.status_code == 409
    assert server.view_count == 0


def test_oversized_image_rejected(monkeypatch):
    server, client, headers = fake_service(monkeypatch)
    job = client.post("/api/atelier/render/submit", headers=headers, json=approved()).json()["job"]
    server.state = "completed"
    server.image_bytes = PNG + b"Z" * MAX_IMAGE_BYTES
    response = client.get(f"/api/atelier/render/{job['prompt_id']}/image", headers=headers)
    assert response.status_code == 502


def test_submission_timeout_does_not_retry_and_is_unknown():
    server = FakeComfy()
    server.timeout_submission = True
    bridge = server.bridge()
    with pytest.raises(RenderBridgeError, match="unknown"):
        asyncio.run(bridge.submit(plan()))
    assert [p for _, p in server.calls].count("/prompt") == 1
    with pytest.raises(RenderBridgeError) as exc:
        asyncio.run(bridge.submit(plan()))
    assert exc.value.status == 409


def test_rejected_graph_not_mislabelled_rendered():
    server = FakeComfy()
    server.fail_submission = True
    bridge = server.bridge()
    with pytest.raises(RenderBridgeError) as exc:
        asyncio.run(bridge.submit(plan()))
    assert exc.value.status == 422
    assert [p for _, p in server.calls].count("/prompt") == 1
