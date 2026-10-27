"""R1-F cloud theme pilot: one small inference, fixed template, distinct verifier.

No GitHub/PR/branch writes, no merge/deploy, no arbitrary shell/user tasks.
Child processes share OS user: NOT independent actor authentication/sandbox.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from .r1b_contract import frozen_bytes, read_spec, spec_digest
from .r1b_cli import _worker_env, run_worker
from .r1f_theme_worker import MODEL, THEMES

HERE = Path(__file__).resolve().parent
MAX_ARTIFACT = 12 * 1024
MAX_CHILD_STDOUT = 4096
MODEL_TIMEOUT = 115
ERROR_CODES = frozenset({
    "WORKER_ARGS", "MODEL_RESPONSE_SIZE_INVALID", "MODEL_RESPONSE_NOT_VALID_JSON",
    "MODEL_RESPONSE_BAD_FIELDS", "MODEL_CHOICE_NOT_ALLOWED", "MODEL_PORT_INVALID",
    "MODEL_HTTP_NOT_OK", "MODEL_HTTP_NOT_JSON", "MODEL_REQUEST_UNAVAILABLE",
    "TRUSTED_TEMPLATE_CHANGED", "TRUSTED_TEMPLATE_SIZE_INVALID",
    "ARTIFACT_DIR_INVALID", "WORKER_IO_OR_INPUT_FAILED",
})


def held(reason: str, stage: str, workspace: str | None = None) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1f.run.v1",
        "status": "HELD",
        "reason": reason,
        "failed_stage": stage,
        "workspace": workspace,
        "model_contribution": "BOUNDED_THEME_ENUM_ONLY",
        "eligible_for_merge": False,
        "automatic_merge": False,
        "repository_writes": "NONE",
        "source_provenance": "GITHUB_RUNNER_LOCAL_SELF_REPORTED_UNATTESTED",
    }


def invoke_model_worker(frozen_path: Path, artifact_dir: Path, workspace: Path,
                        port: int) -> dict[str, Any]:
    try:
        child = subprocess.run(
            [sys.executable, "-S", "-B", str(HERE / "r1f_theme_worker.py"),
             str(frozen_path), str(artifact_dir), str(port)],
            env=_worker_env(), cwd=str(workspace), shell=False, check=False,
            capture_output=True, text=True, timeout=MODEL_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "ERROR", "reason": "WORKER_TIMED_OUT_OR_UNAVAILABLE"}
    if len(child.stdout) > MAX_CHILD_STDOUT:
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    try:
        data = json.loads(child.stdout)
    except (ValueError, TypeError):
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    if not isinstance(data, dict):
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    if child.returncode:
        reason = data.get("reason")
        if data.get("status") == "ERROR" and reason in ERROR_CODES:
            return {"status": "ERROR", "reason": reason}
        return {"status": "ERROR", "reason": "WORKER_FAILED"}
    return data


def run_theme_pilot(spec_path: Path, digest: str, *, model: str = MODEL,
                    port: int = 11434, scratch_root: Path | None = None) -> dict[str, Any]:
    try:
        spec = read_spec(spec_path)
        if digest != spec_digest(spec) or model != MODEL or type(port) is not int or not 1024 <= port <= 65535:
            return held("SPEC_MODEL_OR_PORT_NOT_APPROVED", "PRECHECK")
        workspace = Path(tempfile.mkdtemp(
            prefix="agentora-r1f-cloud-",
            dir=str(scratch_root) if scratch_root is not None else None,
        ))
        path = str(workspace)
        artifact_dir = workspace / "artifact"
        artifact_dir.mkdir()
        frozen_path = workspace / "frozen-spec.json"
        frozen_path.write_bytes(frozen_bytes(spec))
        candidate = invoke_model_worker(frozen_path, artifact_dir, workspace, port)
        if candidate.get("status") != "MODEL_THEME_PROPOSED_ARTIFACT_BUILT":
            return held(candidate.get("reason", "WORKER_UNKNOWN_FAILURE"), "MODEL_OR_TEMPLATE", path)
        if (candidate.get("worker") != "cloud-model-theme-and-fixed-template-builder-process"
                or candidate.get("model") != model
                or candidate.get("theme") not in THEMES
                or candidate.get("spec_digest") != digest
                or candidate.get("artifact") != "index.html"
                or candidate.get("model_contribution") != "BOUNDED_THEME_ENUM_ONLY"):
            return held("WORKER_CLAIMS_MISMATCH", "MODEL_OR_TEMPLATE", path)
        artifact = artifact_dir / "index.html"
        if artifact.is_symlink() or not artifact.is_file():
            return held("ARTIFACT_MISSING_OR_SYMLINK", "ARTIFACT", path)
        with artifact.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT + 1)
        if not raw or len(raw) > MAX_ARTIFACT:
            return held("ARTIFACT_SIZE_INVALID", "ARTIFACT", path)
        artifact_sha = hashlib.sha256(raw).hexdigest()
        if candidate.get("artifact_sha256") != artifact_sha:
            return held("ARTIFACT_SHA_MISMATCH", "ARTIFACT", path)
        verified = run_worker(
            "r1b_verifier_worker.py",
            [str(frozen_path), str(artifact), artifact_sha], workspace,
        )
        if (verified.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or verified.get("worker") != "independent-fixture-verifier-process"
                or verified.get("spec_digest") != digest
                or verified.get("artifact_sha256") != artifact_sha
                or verified.get("artifact") != "index.html"):
            return held("STATIC_CHECKS_REFUSED", "INDEPENDENT_VERIFIER", path)
        if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != artifact_sha:
            return held("ARTIFACT_CHANGED_AFTER_VERIFICATION", "ARTIFACT", path)
        receipt = {
            "schema": "agentora.devboard.r1f.run.v1",
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "workspace": path,
            "spec_digest": digest,
            "artifact": "artifact/index.html",
            "artifact_sha256": artifact_sha,
            "model": MODEL, "theme": candidate["theme"],
            "model_contribution": "BOUNDED_THEME_ENUM_ONLY",
            "builder": "CANNED_ESCAPED_HTML_TEMPLATE_WITH_ALLOWLISTED_PALETTE",
            "verifier": "independent-fixture-verifier-process",
            "source_provenance": "GITHUB_RUNNER_LOCAL_SELF_REPORTED_UNATTESTED",
            "role_identity_authenticated": False,
            "eligible_for_merge": False, "automatic_merge": False,
            "repository_writes": "NONE", "human_review_required": True,
        }
        with (workspace / "review-receipt.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        return receipt
    except (OSError, ValueError, TypeError):
        return held("CLOUD_WORKSPACE_FAILURE", "WORKSPACE")


def recheck_theme(workspace: Path) -> dict[str, Any]:
    """Read-only second independent-process verifier against frozen spec."""
    try:
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("INVALID_WORKSPACE")
        spec_file = workspace / "frozen-spec.json"
        receipt_file = workspace / "review-receipt.json"
        artifact_dir = workspace / "artifact"
        artifact = artifact_dir / "index.html"
        if (spec_file.is_symlink() or receipt_file.is_symlink() or artifact_dir.is_symlink()
                or artifact.is_symlink() or not artifact_dir.is_dir()):
            raise ValueError("INVALID_SYMLINK")
        spec = read_spec(spec_file)
        digest = spec_digest(spec)
        with receipt_file.open("rb") as stream:
            receipt_raw = stream.read(8193)
        if len(receipt_raw) > 8192:
            raise ValueError("RECEIPT_SIZE_INVALID")
        receipt = json.loads(receipt_raw.decode("utf-8"))
        if (not isinstance(receipt, dict)
                or receipt.get("schema") != "agentora.devboard.r1f.run.v1"
                or receipt.get("status") != "REVIEW_READY_NOT_AUTHORIZED"
                or receipt.get("spec_digest") != digest
                or receipt.get("artifact") != "artifact/index.html"
                or receipt.get("theme") not in THEMES
                or receipt.get("model") != MODEL
                or receipt.get("model_contribution") != "BOUNDED_THEME_ENUM_ONLY"
                or receipt.get("eligible_for_merge") is not False
                or receipt.get("automatic_merge") is not False
                or receipt.get("repository_writes") != "NONE"):
            raise ValueError("RECEIPT_INVALID")
        with artifact.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT + 1)
        sha = hashlib.sha256(raw).hexdigest()
        if len(raw) == 0 or len(raw) > MAX_ARTIFACT or receipt.get("artifact_sha256") != sha:
            raise ValueError("ARTIFACT_SHA_CHANGED")
        verdict = run_worker("r1b_verifier_worker.py",
                             [str(spec_file), str(artifact), sha], workspace)
        if (verdict.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or verdict.get("spec_digest") != digest
                or verdict.get("artifact_sha256") != sha
                or verdict.get("worker") != "independent-fixture-verifier-process"):
            raise ValueError("STATIC_RECHECK_REFUSED")
        if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != sha:
            raise ValueError("ARTIFACT_CHANGED_DURING_RECHECK")
        return {
            "status": "LOCAL_RECHECK_PASS_REVIEW_ONLY",
            "spec_digest": digest, "artifact_sha256": sha,
            "model": MODEL, "theme": receipt["theme"],
            "model_contribution": "BOUNDED_THEME_ENUM_ONLY",
            "eligible_for_merge": False,
            "automatic_merge": False,
            "source_provenance": "GITHUB_RUNNER_LOCAL_SELF_REPORTED_UNATTESTED",
        }
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {"status": "HELD", "reason": "RECHECK_REFUSED",
                "eligible_for_merge": False, "automatic_merge": False}
