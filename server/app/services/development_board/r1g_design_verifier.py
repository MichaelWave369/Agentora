"""R1-G separate child: strict design decision and exact HTML reconstruction.

This checks byte-for-byte conformance to the allowlisted renderer. The existing
R1-B separate parser independently checks safety/semantics before this step.
No model calls, HTML execution or filesystem writes occur here.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

if __package__:
    from .r1b_contract import read_spec, spec_digest
    from .r1g_design_worker import MODEL, DesignRefusal, render_design, validate_choices
else:
    from r1b_contract import read_spec, spec_digest
    from r1g_design_worker import MODEL, DesignRefusal, render_design, validate_choices

HEX64 = re.compile(r"^[0-9a-f]{64}$")
FIELDS = frozenset((
    "schema", "model", "spec_digest", "choices", "model_contribution", "authority",
))


def verify_design(spec: dict[str, str], decision: object, raw: bytes, expected_sha: str) -> dict:
    if not isinstance(decision, dict) or set(decision) != FIELDS:
        raise ValueError("DECISION_FIELDS_INVALID")
    digest = spec_digest(spec)
    if (decision.get("schema") != "agentora.devboard.r1g.decision.v1"
            or decision.get("model") != MODEL
            or decision.get("spec_digest") != digest
            or decision.get("authority") != "NONE"
            or decision.get("model_contribution") != "THREE_BOUNDED_ENUM_DECISIONS_ONLY"):
        raise ValueError("DECISION_SCOPE_INVALID")
    try:
        choices = validate_choices(decision["choices"])
        expected_raw = render_design(spec, choices)
    except (DesignRefusal, KeyError) as exc:
        raise ValueError("DECISION_VALUES_REFUSED") from exc
    if (not isinstance(expected_sha, str) or not HEX64.fullmatch(expected_sha)
            or not 0 < len(raw) <= 12 * 1024):
        raise ValueError("ARTIFACT_SIZE_OR_DIGEST_INVALID")
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha:
        raise ValueError("ARTIFACT_SHA_MISMATCH")
    if raw != expected_raw:
        raise ValueError("ARTIFACT_NOT_EXACT_APPROVED_DESIGN")
    return {
        "schema": "agentora.devboard.r1g.verify.v1",
        "status": "DESIGN_BINDING_PASS_SELF_REPORTED",
        "worker": "independent-process-exact-design-contract-verifier",
        "spec_digest": digest,
        "artifact": "index.html",
        "artifact_sha256": actual,
        "choices": choices,
        "authority": "NONE",
    }


def main(args: list[str]) -> int:
    if len(args) != 4:
        print(json.dumps({"status": "ERROR", "reason": "VERIFIER_ARGS"}))
        return 2
    try:
        spec_path, decision_path, artifact_path, expected = map(str, args)
        spec_file, decision_file, artifact_file = map(
            Path, (spec_path, decision_path, artifact_path)
        )
        if (spec_file.is_symlink() or decision_file.is_symlink()
                or artifact_file.is_symlink() or artifact_file.name != "index.html"
                or not decision_file.is_file() or not artifact_file.is_file()):
            raise ValueError("INVALID_VERIFIER_FILE_PATH")
        spec = read_spec(spec_file)
        with decision_file.open("rb") as stream:
            encoded = stream.read(4097)
        if len(encoded) > 4096:
            raise ValueError("DECISION_FILE_TOO_LARGE")
        decision = json.loads(encoded.decode("utf-8"))
        with artifact_file.open("rb") as stream:
            raw = stream.read(12 * 1024 + 1)
        print(json.dumps(verify_design(spec, decision, raw, expected), sort_keys=True))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError):
        print(json.dumps({"status": "ERROR", "reason": "DESIGN_CONTRACT_REFUSED", "authority": "NONE"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
