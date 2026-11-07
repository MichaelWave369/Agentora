"""PhiAtelier's intentionally narrow, opt-in, loopback-only ComfyUI pilot.

One application process, one active job, no persistence, no publishing,
no arbitrary ComfyUI workflows, no remote endpoint configuration.
This module only accepts the digest-pinned graph from render_plan.py.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

MAX_JSON_BYTES = 1_048_576
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_JOBS = 16
IMAGE_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().-]{0,180}\.(?:png|jpg|jpeg|webp)\Z", re.I)
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


class RenderBridgeError(ValueError):
    def __init__(self, detail: str, status: int = 422):
        super().__init__(detail)
        self.status = status


def configured_port() -> int:
    """ComfyUI is pinned to IPv4 loopback regardless of environment."""
    value = os.environ.get("AGENTORA_ATELIER_COMFY_PORT", "8188")
    if not value.isascii() or not value.isdecimal():
        raise RenderBridgeError("ComfyUI port must be numeric", 503)
    number = int(value)
    if not 1024 <= number <= 65535:
        raise RenderBridgeError("ComfyUI port must be 1024..65535", 503)
    return number


def _canonical_uuid(value: str) -> str:
    try:
        parsed = str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RenderBridgeError("invalid render job ID", 422) from exc
    if parsed != value:
        raise RenderBridgeError("job ID must be canonical UUID", 422)
    return parsed


class ComfyRenderBridge:
    """A process-local job ledger. Use ONE Agentora backend worker.

    An HTTP response failure after POST /prompt is *ambiguous*; preserve the
    prompt_id as submission_unknown instead of automatically retrying.
    """

    def __init__(self, client_factory: Callable[[int], httpx.AsyncClient] | None = None):
        self._factory = client_factory or self._default_client
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._used_digests: set[str] = set()
        self._active: str | None = None

    @staticmethod
    def _default_client(port: int) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=httpx.Timeout(15.0, connect=3.0),
            trust_env=False,
            follow_redirects=False,
        )

    async def _json(
        self, method: str, port: int, route: str, payload: dict | None = None
    ) -> Any:
        try:
            async with self._factory(port) as client:
                async with client.stream(method, route, json=payload) as response:
                    if response.is_redirect:
                        raise RenderBridgeError("ComfyUI redirected a local request", 503)
                    if response.status_code >= 400:
                        raise RenderBridgeError(
                            "ComfyUI rejected the request" if response.status_code < 500
                            else "ComfyUI server error",
                            422 if response.status_code < 500 else 503,
                        )
                    body = bytearray()
                    async for piece in response.aiter_bytes():
                        body.extend(piece)
                        if len(body) > MAX_JSON_BYTES:
                            raise RenderBridgeError("ComfyUI JSON response too large", 502)
            return json.loads(body)
        except RenderBridgeError:
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise RenderBridgeError("local ComfyUI unavailable or returned malformed JSON", 503) from exc

    def _snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                raise RenderBridgeError("render job not found in this Agentora process", 404)
            return dict(record)

    async def submit(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Queue exactly one approved graph, after checking installed checkpoints."""
        digest = plan["workflow_digest"]
        graph = plan["workflow"]
        port = configured_port()
        with self._lock:
            if digest in self._used_digests:
                raise RenderBridgeError("that workflow digest was already submitted; change the seed for another render", 409)
            if self._active is not None:
                raise RenderBridgeError("an earlier render is still active or unresolved", 409)
            if len(self._jobs) >= MAX_JOBS:
                raise RenderBridgeError("session render ledger full; restart the private service after recording outputs", 409)
            self._active = "preflight"
            self._used_digests.add(digest)

        # Check exact locally advertised checkpoint before any GPU work is queued.
        try:
            models = await self._json("GET", port, "/models/checkpoints")
            model_name = graph["4"]["inputs"]["ckpt_name"]
            if not isinstance(models, list) or model_name not in models:
                raise RenderBridgeError("configured checkpoint is not installed in local ComfyUI", 422)
        except Exception:
            with self._lock:
                self._active = None
                self._used_digests.discard(digest)
            raise

        job_id = str(uuid.uuid4())
        with self._lock:
            self._active = job_id
            self._jobs[job_id] = {
                "prompt_id": job_id,
                "workflow_digest": digest,
                "status": "submission_unknown",
                "render_status": "unverified",
                "image_ready": False,
            }
        try:
            reply = await self._json("POST", port, "/prompt", {
                "prompt": graph, "client_id": str(uuid.uuid4()), "prompt_id": job_id,
            })
        except RenderBridgeError as exc:
            # 422 means ComfyUI explicitly rejected the graph, unlike a timeout.
            with self._lock:
                if exc.status == 422:
                    self._jobs[job_id]["status"] = "rejected"
                    self._active = None
                else:
                    self._jobs[job_id]["status"] = "submission_unknown"
            raise RenderBridgeError(
                "ComfyUI rejected the graph" if exc.status == 422
                else f"submission outcome unknown; inspect job {job_id} before any retry",
                exc.status,
            ) from exc
        if not isinstance(reply, dict) or reply.get("prompt_id") != job_id:
            # The server may have queued the job despite a malformed receipt.
            raise RenderBridgeError(f"submission receipt invalid; inspect job {job_id}", 502)
        with self._lock:
            self._jobs[job_id]["status"] = "queued"
        return self._snapshot(job_id)

    @staticmethod
    def _in_queue(items: Any, job_id: str) -> bool:
        return isinstance(items, list) and any(
            isinstance(row, list) and len(row) >= 2 and row[1] == job_id
            for row in items
        )

    async def status(self, job_id: str) -> dict[str, Any]:
        job_id = _canonical_uuid(job_id)
        self._snapshot(job_id)  # Restrict reads to jobs submitted by this process.
        port = configured_port()
        history = await self._json("GET", port, f"/history/{job_id}")
        current = history.get(job_id) if isinstance(history, dict) else None
        images: list[dict] = []
        state = "unknown"
        if isinstance(current, dict):
            info = current.get("status", {})
            state_info = info.get("status_str", "") if isinstance(info, dict) else ""
            outputs = current.get("outputs", {})
            save_node = outputs.get("9", {}) if isinstance(outputs, dict) else {}
            refs = save_node.get("images", []) if isinstance(save_node, dict) else []
            if isinstance(refs, list):
                for ref in refs[:1]:
                    if (isinstance(ref, dict) and ref.get("type") == "output"
                            and ref.get("subfolder") == ""
                            and isinstance(ref.get("filename"), str)
                            and IMAGE_FILE.fullmatch(ref["filename"])
                            and ref["filename"].startswith("PhiAtelier_")):
                        images.append({
                            "filename": ref["filename"], "type": "output", "subfolder": "",
                        })
            if state_info == "success" and images:
                state = "completed"
            elif state_info == "error" or (isinstance(info, dict) and info.get("completed") is True and not images):
                state = "failed"
            elif state_info in ("running", "pending"):
                state = state_info
        if state == "unknown":
            queue = await self._json("GET", port, "/queue")
            if isinstance(queue, dict):
                if self._in_queue(queue.get("queue_running"), job_id):
                    state = "running"
                elif self._in_queue(queue.get("queue_pending"), job_id):
                    state = "queued"

        with self._lock:
            record = self._jobs[job_id]
            record["status"] = state
            record["image_ready"] = bool(images and state == "completed")
            record["render_status"] = "rendered" if state == "completed" else "unverified"
            if state in ("completed", "failed") and self._active == job_id:
                self._active = None
            return dict(record)

    async def image(self, job_id: str) -> tuple[bytes, str]:
        record = await self.status(job_id)
        if not record["image_ready"]:
            raise RenderBridgeError("no completed image available", 409)
        # Recheck the exact original output filename; no caller-controlled path.
        history = await self._json("GET", configured_port(), f"/history/{job_id}")
        ref = history[job_id]["outputs"]["9"]["images"][0]
        filename = ref.get("filename")
        if (ref.get("type") != "output" or ref.get("subfolder") != ""
                or not isinstance(filename, str) or not IMAGE_FILE.fullmatch(filename)
                or not filename.startswith("PhiAtelier_")):
            raise RenderBridgeError("unsafe image metadata", 502)
        uri = "/view?" + urlencode({"filename": filename, "subfolder": "", "type": "output"})
        try:
            async with self._factory(configured_port()) as client:
                async with client.stream("GET", uri) as response:
                    if response.status_code != 200:
                        raise RenderBridgeError("image is not available", 503)
                    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if mime not in ALLOWED_TYPES:
                        raise RenderBridgeError("image response has unsupported type", 502)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_IMAGE_BYTES:
                            raise RenderBridgeError("image response exceeds 16 MB", 502)
            if not body:
                raise RenderBridgeError("image response was empty", 502)
            signatures = {
                "image/png": bytes(body[:8]) == b"\x89PNG\r\n\x1a\n",
                "image/jpeg": bytes(body[:2]) == b"\xff\xd8",
                "image/webp": (bytes(body[:4]) == b"RIFF" and bytes(body[8:12]) == b"WEBP"),
            }
            if not signatures[mime]:
                raise RenderBridgeError("downloaded image signature does not match MIME type", 502)
            return bytes(body), mime
        except RenderBridgeError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise RenderBridgeError("local image retrieval failed", 503) from exc

    async def cancel(self, job_id: str) -> dict[str, Any]:
        current = await self.status(job_id)
        if current["status"] == "queued":
            await self._json("POST", configured_port(), "/queue", {"delete": [job_id]})
        elif current["status"] == "running":
            await self._json("POST", configured_port(), "/interrupt", {"prompt_id": job_id})
        else:
            raise RenderBridgeError("only a known queued or running job can be cancelled", 409)
        # A request for cancellation is NOT a verified cancellation receipt.
        with self._lock:
            self._jobs[job_id]["status"] = "cancellation_requested"
        return self._snapshot(job_id)
