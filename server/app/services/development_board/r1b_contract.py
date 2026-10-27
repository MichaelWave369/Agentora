"""R1-B limited local fixture specification, with no authority or executable inputs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "agentora.devboard.r1b.fixture-spec.v1"
FIELDS = ("schema", "title", "headline", "description", "button_label")
MAX_BYTES = 4096
LIMITS = {"title": 100, "headline": 140, "description": 320, "button_label": 48}


def validate_spec(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError("INVALID_SPEC_FIELDS")
    if value.get("schema") != SCHEMA:
        raise ValueError("UNSUPPORTED_SPEC_SCHEMA")
    for key, limit in LIMITS.items():
        text = value[key]
        if (not isinstance(text, str) or not text.strip() or len(text) > limit or
                any(ord(char) < 32 or ord(char) == 127 for char in text)):
            raise ValueError("INVALID_SPEC_" + key.upper())
    return {name: value[name] for name in FIELDS}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, val in pairs:
        if key in result:
            raise ValueError("DUPLICATE_SPEC_KEY")
        result[key] = val
    return result


def parse_spec(raw: bytes) -> dict[str, str]:
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("SPEC_TOO_LARGE_OR_INVALID")
    try:
        return validate_spec(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("SPEC_INVALID_JSON") from exc


def read_spec(path: Path) -> dict[str, str]:
    # A user-specified path is read only, never used as a build target.
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    return parse_spec(raw)


def frozen_bytes(spec: dict[str, str]) -> bytes:
    return json.dumps(
        validate_spec(spec), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def spec_digest(spec: dict[str, str]) -> str:
    return hashlib.sha256(frozen_bytes(spec)).hexdigest()
