"""R1-D: operator-guided local Ollama field test and read-only receipt recheck.

No web endpoint, no automatic execution, no GitHub, PhiBot, GitPorch or merge
writes. A recorded field self-report is NOT independent execution attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable

from .r1b_contract import read_spec, spec_digest
from .r1b_cli import run_worker
from .r1c_cli import plan, run_pilot
from .r1c_model_worker import checked_model, checked_port

HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_HTTP = 65536
MAX_RECEIPT = 8192
MAX_ARTIFACT = 12 * 1024
RECEIPT_FILE = "review-receipt.json"
FIELD_FILE = "field-qualification.json"
EXPECTED_CHECKS = frozenset({
    "sha256", "spec-binding", "html-syntax", "no-scripts-or-external",
    "semantic-content", "skip-navigation", "viewport",
})


def held(reason: str) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1d.field.v1",
        "status": "HELD",
        "reason": reason,
        "classification": "LOCAL_SELF_REPORTED_NOT_ATTESTED",
        "eligible_for_merge": False,
        "automatic_merge": False,
    }


def preflight_model(model: str, port: int) -> dict[str, str]:
    """Operator-approved GET to fixed localhost /api/tags, no proxies or redirects."""
    checked_model(model)
    checked_port(port)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/api/tags", headers={
            "Accept": "application/json", "User-Agent": "Agentora-Devboard-R1D/0.1",
        })
        response = conn.getresponse()
        if response.status != 200:
            return {"status": "HELD", "reason": "LOCAL_OLLAMA_NOT_READY"}
        if "application/json" not in response.getheader("Content-Type", "").lower():
            return {"status": "HELD", "reason": "OLLAMA_TAGS_INVALID_CONTENT_TYPE"}
        raw = response.read(MAX_HTTP + 1)
        if len(raw) > MAX_HTTP:
            return {"status": "HELD", "reason": "OLLAMA_TAGS_TOO_LARGE"}
        data = json.loads(raw.decode("utf-8"))
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list) or len(models) > 200:
            return {"status": "HELD", "reason": "OLLAMA_TAGS_INVALID"}
        names = set()
        for item in models:
            if not isinstance(item, dict):
                return {"status": "HELD", "reason": "OLLAMA_TAGS_INVALID"}
            for field in ("name", "model"):
                name = item.get(field)
                if isinstance(name, str) and len(name) <= 160:
                    names.add(name)
        if model not in names:
            return {"status": "HELD", "reason": "REQUESTED_MODEL_NOT_INSTALLED"}
        return {"status": "READY", "model": model}
    except (OSError, TimeoutError, http.client.HTTPException, ValueError, UnicodeError):
        return {"status": "HELD", "reason": "OLLAMA_PREFLIGHT_UNAVAILABLE"}
    finally:
        conn.close()


def _read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("MISSING_OR_SYMLINK_FILE")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("FILE_TOO_LARGE")
    return data


def recheck_workspace(workspace: Path) -> dict[str, Any]:
    """Independently re-read fixed local artifacts; no writing or network calls."""
    if not isinstance(workspace, Path) or workspace.is_symlink() or not workspace.is_dir():
        return held("WORKSPACE_MISSING_OR_SYMLINK")
    try:
        frozen_path = workspace / "frozen-spec.json"
        artifact_dir = workspace / "artifact"
        artifact = artifact_dir / "index.html"
        if artifact_dir.is_symlink() or not artifact_dir.is_dir():
            return held("ARTIFACT_DIRECTORY_INVALID")
        spec = read_spec(frozen_path) if not frozen_path.is_symlink() else None
        if spec is None:
            return held("FROZEN_SPEC_SYMLINK")
        digest = spec_digest(spec)
        raw_receipt = _read_bounded(workspace / RECEIPT_FILE, MAX_RECEIPT)
        receipt = json.loads(raw_receipt.decode("utf-8"))
        if not isinstance(receipt, dict):
            return held("RECEIPT_INVALID_JSON")
        if (receipt.get("schema") != "agentora.devboard.r1c.run.v1"
                or receipt.get("status") != "REVIEW_READY_NOT_AUTHORIZED"
                or receipt.get("spec_digest") != digest
                or receipt.get("artifact") != "artifact/index.html"
                or receipt.get("eligible_for_merge") is not False
                or receipt.get("automatic_merge") is not False
                or receipt.get("role_identity_authenticated") is not False
                or receipt.get("repository_writes") != "NONE"
                or receipt.get("source_provenance") != "LOCAL_SELF_REPORTED_UNATTESTED"
                or receipt.get("model_worker") != "local-ollama-html-proposal-process"
                or receipt.get("static_verifier") != "independent-fixture-verifier-process"
                or not isinstance(receipt.get("model"), str)):
            return held("RECEIPT_SCOPE_OR_SPEC_MISMATCH")
        checked_model(receipt["model"])
        raw_artifact = _read_bounded(artifact, MAX_ARTIFACT)
        actual_sha = hashlib.sha256(raw_artifact).hexdigest()
        if len(raw_artifact) == 0 or receipt.get("artifact_sha256") != actual_sha:
            return held("ARTIFACT_SHA_CHANGED")
        checks = receipt.get("static_checks")
        if (not isinstance(checks, list) or set(checks) != EXPECTED_CHECKS
                or len(checks) != len(EXPECTED_CHECKS)):
            return held("RECEIPT_CHECKS_MISSING")
        checked = run_worker(
            "r1b_verifier_worker.py",
            [str(frozen_path), str(artifact), actual_sha], workspace,
        )
        if (checked.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or checked.get("spec_digest") != digest
                or checked.get("artifact_sha256") != actual_sha
                or checked.get("worker") != "independent-fixture-verifier-process"):
            return held("RECHECK_VERIFIER_REFUSED")
        if artifact.is_symlink() or hashlib.sha256(
                _read_bounded(artifact, MAX_ARTIFACT)).hexdigest() != actual_sha:
            return held("ARTIFACT_CHANGED_DURING_RECHECK")
        return {
            "schema": "agentora.devboard.r1d.field.v1",
            "status": "LOCAL_RECHECK_PASS_REVIEW_ONLY",
            "classification": "LOCAL_SELF_REPORTED_NOT_ATTESTED",
            "spec_digest": digest,
            "artifact_sha256": actual_sha,
            "receipt_sha256": hashlib.sha256(raw_receipt).hexdigest(),
            "model_identifier": receipt["model"],
            "static_checks": sorted(EXPECTED_CHECKS),
            "eligible_for_merge": False,
            "automatic_merge": False,
            "human_visual_review": "NOT_PERFORMED_BY_THIS_TOOL",
            "local_model_observation": "RECEIPT_CLAIM_NOT_INDEPENDENTLY_WITNESSED",
            "remote_ci_observation": "NOT_OBSERVED",
        }
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        return held("LOCAL_RECHECK_FAILED")


def run_guided(spec_path: Path, *, model: str = "qwen3.5:9b", port: int = 11434,
               confirm: Callable[[str], str] = input) -> dict[str, Any]:
    """Interactive; absolutely no network/write before exact human acknowledgement."""
    try:
        planned = plan(spec_path, model, port)
        spec = read_spec(spec_path)
    except (OSError, ValueError, TypeError):
        return held("INVALID_SPEC_MODEL_OR_PORT")
    digest = planned["frozen_spec_digest"]
    print(json.dumps({
        "action": "LOCAL_OLLAMA_FIELD_PILOT",
        "spec": spec,
        "digest": digest,
        "model": model,
        "port": port,
        "writes": "NEW_TEMPORARY_FOLDER_ONLY",
        "network": "127.0.0.1_ONLY_AFTER_ACK",
        "merge_authority": False,
    }, indent=2, ensure_ascii=False))
    try:
        answer = confirm("Type APPROVE " + digest[:16] + " to run the local model: ")
    except (EOFError, KeyboardInterrupt):
        return held("OPERATOR_DECLINED_OR_NOT_INTERACTIVE")
    if answer.strip() != "APPROVE " + digest[:16]:
        return held("OPERATOR_DECLINED_OR_MISMATCHED_ACK")
    preflight = preflight_model(model, port)
    if preflight["status"] != "READY":
        return held(preflight.get("reason", "PREFLIGHT_REFUSED"))
    result = run_pilot(spec_path, digest, model=model, port=port)
    if result.get("status") != "REVIEW_READY_NOT_AUTHORIZED":
        return held(result.get("reason", "LOCAL_MODEL_PROPOSAL_HELD"))
    workspace = Path(result["workspace"])
    reviewed = recheck_workspace(workspace)
    if reviewed["status"] != "LOCAL_RECHECK_PASS_REVIEW_ONLY":
        return reviewed
    # This note is intentionally a SELF-report, NOT a certification of a human test.
    field = {
        **reviewed,
        "observed_at_local_clock_untrusted": datetime.now(timezone.utc).isoformat(),
        "human_visual_review": "PENDING",
        "code_brown_first_use_test": "NOT_PERFORMED",
    }
    try:
        with (workspace / FIELD_FILE).open("x", encoding="utf-8") as stream:
            json.dump(field, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except OSError:
        return held("FIELD_REPORT_COULD_NOT_BE_SAVED")
    return {"field_result": field, "local_workspace": str(workspace),
            "qualification_saved": FIELD_FILE}


def main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(description="R1-D guided Windows-local Ollama pilot")
    sub = parser.add_subparsers(dest="operation", required=True)
    guided = sub.add_parser("guided", help="Explicit interactive model run, then self-recheck")
    guided.add_argument("spec", type=Path)
    guided.add_argument("--model", default="qwen3.5:9b")
    guided.add_argument("--ollama-port", type=int, default=11434)
    inspect = sub.add_parser("recheck", help="Read-only recheck of an existing R1-C workspace")
    inspect.add_argument("workspace", type=Path)
    opts = parser.parse_args(args)
    if opts.operation == "guided":
        result = run_guided(opts.spec, model=opts.model, port=opts.ollama_port)
        status = result.get("field_result", {}).get("status") if "field_result" in result else "HELD"
    else:
        result = recheck_workspace(opts.workspace)
        status = result["status"]
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if status == "LOCAL_RECHECK_PASS_REVIEW_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
