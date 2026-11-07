"""ComfyUI text-to-image API graph *preview*; no dispatch or GPU execution.

Based on ComfyUI's public basic_api_example.py. A real ComfyUI installation
must independently validate the model, supported nodes and latent dimensions.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

DIMENSIONS = {
    "16:9": (1024, 576),
    "3:4": (768, 1024),
    "1:1": (768, 768),
}
CHECKPOINT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()._-]{0,120}\.safetensors\Z")
MAX_PROMPT = 3000
MAX_NEGATIVE = 850


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def build_render_plan(
    *,
    positive_prompt: str,
    negative_prompt: str,
    checkpoint: str,
    aspect_ratio: str = "16:9",
    seed: int = 369,
    steps: int = 24,
    cfg: float = 7.0,
) -> dict[str, Any]:
    """Build an inspectable draft workflow for *future* operator-approved use."""
    if not isinstance(positive_prompt, str) or not 1 <= len(positive_prompt.strip()) <= MAX_PROMPT:
        raise ValueError("positive prompt must contain 1..3000 characters")
    if not isinstance(negative_prompt, str) or len(negative_prompt) > MAX_NEGATIVE:
        raise ValueError("negative prompt exceeds 850 characters")
    if any(ord(ch) == 0 for ch in positive_prompt + negative_prompt):
        raise ValueError("prompts contain invalid control characters")
    if (not isinstance(checkpoint, str) or not CHECKPOINT_PATTERN.fullmatch(checkpoint)
            or ".." in checkpoint):
        raise ValueError("checkpoint must be a safe local safetensors filename")
    if aspect_ratio not in DIMENSIONS:
        raise ValueError("unsupported aspect ratio")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer from 0 through 4294967295")
    if type(steps) is not int or not 8 <= steps <= 40:
        raise ValueError("steps must be an integer from 8 through 40")
    if type(cfg) not in (int, float) or not 1.0 <= cfg <= 12.0:
        raise ValueError("CFG must be a finite number from 1 through 12")
    width, height = DIMENSIONS[aspect_ratio]
    graph = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": checkpoint}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode",
              "inputs": {"text": positive_prompt.strip(), "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative_prompt.strip(), "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": float(cfg),
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
            "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["5", 0],
        }},
        "8": {"class_type": "VAEDecode",
              "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"filename_prefix": "PhiAtelier", "images": ["8", 0]}},
    }
    return {
        "schema_version": "phi.atelier.comfy-plan.v1",
        "workflow_digest": _digest(graph),
        "workflow": graph,
        "status": "DRAFT_NOT_SUBMITTED",
        "render_status": "not_rendered",
        "operator_approval_required": True,
        "execution_enabled": False,
        "server_contacted": False,
        "batch_size": 1,
        "notes": (
            "This is an API-format ComfyUI workflow draft, not a render or "
            "a verified local checkpoint. ComfyUI must validate the graph and "
            "installed model before an operator explicitly queues it."
        ),
    }
