"""R1-G manual cloud design pilot: bounded AI decisions, never arbitrary code.

Separate subprocesses: model + deterministic renderer; independent R1-B HTML
parser; R1-G exact decision binding verifier. No role auth or OS sandbox.
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
from .r1g_design_worker import MODEL, validate_choices, DesignRefusal
from .r1g_design_verifier import FIELDS

HERE = Path(__file__).resolve().parent
MAX_SIZE = 12 * 1024
MAX_STDOUT = 4096
ERROR_CODES = frozenset({
    "MODEL_RESPONSE_SIZE_INVALID", "MODEL_RESPONSE_NOT_JSON",
    "DESIGN_FIELDS_INVALID", "DESIGN_CHOICE_NOT_ALLOWED", "MODEL_PORT_INVALID",
    "MODEL_HTTP_NOT_OK", "MODEL_HTTP_NOT_JSON", "MODEL_REQUEST_UNAVAILABLE",
    "TRUSTED_RENDER_TEMPLATE_CHANGED", "TRUSTED_DESIGN_SIZE_INVALID",
    "SCRATCH_DIRECTORY_INVALID", "WORKER_IO_OR_INPUT_FAILED", "WORKER_ARGS",
})


def held(reason: str, stage: str, workspace: str | None = None) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1g.run.v1",
        "status": "HELD", "reason": reason, "failed_stage": stage,
        "workspace": workspace, "model_contribution": "THREE_BOUNDED_ENUM_DECISIONS_ONLY",
        "eligible_for_merge": False, "automatic_merge": False,
        "repository_writes": "NONE",
        "source_provenance": "GITHUB_RUNNER_SELF_REPORTED_NOT_ATTESTED",
    }


def child(script: str, args: list[str], workspace: Path, timeout: int) -> dict[str, Any]:
    if script not in ("r1g_design_worker.py", "r1g_design_verifier.py"):
        return {"status": "ERROR", "reason": "UNKNOWN_WORKER"}
    try:
        job = subprocess.run(
            [sys.executable, "-S", "-B", str(HERE / script), *args],
            cwd=str(workspace), env=_worker_env(), shell=False, check=False,
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "ERROR", "reason": "WORKER_TIMED_OUT_OR_UNAVAILABLE"}
    if len(job.stdout) > MAX_STDOUT:
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    try:
        response = json.loads(job.stdout)
    except (ValueError, TypeError):
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    if not isinstance(response, dict):
        return {"status": "ERROR", "reason": "WORKER_STDOUT_INVALID"}
    if job.returncode:
        code = response.get("reason")
        if code in ERROR_CODES:
            return {"status": "ERROR", "reason": code}
        return {"status": "ERROR", "reason": "WORKER_REFUSED"}
    return response


def read_limited(path: Path, cap: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("FILE_MISSING_OR_SYMLINK")
    with path.open("rb") as stream:
        data = stream.read(cap + 1)
    if not 0 < len(data) <= cap:
        raise ValueError("FILE_SIZE_INVALID")
    return data


def _valid_decision(decision: object, digest: str) -> dict[str, str]:
    if not isinstance(decision, dict) or set(decision) != FIELDS:
        raise ValueError("DECISION_FIELDS_INVALID")
    if (decision.get("schema") != "agentora.devboard.r1g.decision.v1"
            or decision.get("model") != MODEL
            or decision.get("spec_digest") != digest
            or decision.get("model_contribution") != "THREE_BOUNDED_ENUM_DECISIONS_ONLY"
            or decision.get("authority") != "NONE"):
        raise ValueError("DECISION_SCOPE_INVALID")
    try:
        return validate_choices(decision["choices"])
    except DesignRefusal as exc:
        raise ValueError("DECISION_CHOICE_INVALID") from exc


def run_design_pilot(spec_path: Path, approved_digest: str, *,
                     model: str = MODEL, port: int = 11434,
                     scratch_root: Path | None = None) -> dict[str, Any]:
    try:
        spec = read_spec(spec_path)
        if (approved_digest != spec_digest(spec) or model != MODEL
                or type(port) is not int or not 1024 <= port <= 65535):
            return held("SPEC_MODEL_OR_PORT_NOT_APPROVED", "PRECHECK")
        workspace = Path(tempfile.mkdtemp(
            prefix="agentora-devboard-r1g-",
            dir=str(scratch_root) if scratch_root is not None else None,
        ))
    except (OSError, TypeError, ValueError):
        return held("SCRATCH_CREATION_REFUSED", "PRECHECK")
    location = str(workspace)
    try:
        frozen = workspace / "frozen-spec.json"
        frozen.write_bytes(frozen_bytes(spec))
        artifact_dir = workspace / "artifact"
        artifact_dir.mkdir()
        response = child("r1g_design_worker.py",
                         [str(frozen), str(artifact_dir), str(port)],
                         workspace, timeout=115)
        if response.get("status") != "DESIGN_BUILT_UNVERIFIED":
            return held(response.get("reason", "MODEL_WORKER_REFUSED"),
                        "MODEL_OR_RENDERER", location)
        sha = response.get("artifact_sha256")
        choice_path = workspace / "design-decision.json"
        decision_raw = read_limited(choice_path, 4096)
        decision = json.loads(decision_raw.decode("utf-8"))
        choices = _valid_decision(decision, approved_digest)
        if (response.get("worker") != "cloud-model-design-choice-and-fixed-renderer-process"
                or response.get("model") != MODEL
                or response.get("spec_digest") != approved_digest
                or response.get("choices") != choices
                or response.get("artifact") != "index.html"
                or response.get("model_contribution") != "THREE_BOUNDED_ENUM_DECISIONS_ONLY"):
            return held("WORKER_CLAIMS_MISMATCH", "DECISION", location)
        artifact = artifact_dir / "index.html"
        raw = read_limited(artifact, MAX_SIZE)
        if sha != hashlib.sha256(raw).hexdigest():
            return held("ARTIFACT_HASH_MISMATCH", "ARTIFACT", location)
        static = run_worker("r1b_verifier_worker.py",
                            [str(frozen), str(artifact), sha], workspace)
        if (static.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or static.get("worker") != "independent-fixture-verifier-process"
                or static.get("spec_digest") != approved_digest
                or static.get("artifact_sha256") != sha):
            return held("HTML_SEMANTIC_VERIFIER_REFUSED", "HTML_VERIFIER", location)
        binding = child("r1g_design_verifier.py",
                        [str(frozen), str(choice_path), str(artifact), sha],
                        workspace, timeout=12)
        if (binding.get("status") != "DESIGN_BINDING_PASS_SELF_REPORTED"
                or binding.get("worker") != "independent-process-exact-design-contract-verifier"
                or binding.get("spec_digest") != approved_digest
                or binding.get("artifact_sha256") != sha
                or binding.get("choices") != choices):
            return held("DESIGN_CONTRACT_VERIFIER_REFUSED", "DESIGN_VERIFIER", location)
        if hashlib.sha256(read_limited(artifact, MAX_SIZE)).hexdigest() != sha:
            return held("ARTIFACT_CHANGED_AFTER_CHECKS", "ARTIFACT", location)
        receipt = {
            "schema": "agentora.devboard.r1g.run.v1",
            "status": "REVIEW_READY_NOT_AUTHORIZED", "workspace": location,
            "spec_digest": approved_digest,
            "artifact": "artifact/index.html", "artifact_sha256": sha,
            "decision": "design-decision.json",
            "decision_sha256": hashlib.sha256(decision_raw).hexdigest(),
            "model": MODEL, "choices": choices,
            "model_contribution": "THREE_BOUNDED_ENUM_DECISIONS_ONLY",
            "renderer": "BOUNDED_DETERMINISTIC_RESPONSIVE_HTML",
            "html_verifier": "independent-fixture-verifier-process",
            "design_verifier": "independent-process-exact-design-contract-verifier",
            "source_provenance": "GITHUB_RUNNER_SELF_REPORTED_NOT_ATTESTED",
            "role_identity_authenticated": False,
            "eligible_for_merge": False, "automatic_merge": False,
            "repository_writes": "NONE", "human_review_required": True,
        }
        with (workspace / "review-receipt.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        return receipt
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return held("WORKSPACE_EVIDENCE_INVALID", "WORKSPACE", location)


def recheck_design(workspace: Path) -> dict[str, Any]:
    """Read-only: two fresh independent subprocess validations and hashes."""
    try:
        if workspace.is_symlink() or not workspace.is_dir():
            raise ValueError("BAD_WORKSPACE")
        spec_path = workspace / "frozen-spec.json"
        choice_path = workspace / "design-decision.json"
        receipt_path = workspace / "review-receipt.json"
        artifact = workspace / "artifact/index.html"
        if (spec_path.is_symlink() or (workspace / "artifact").is_symlink()
                or choice_path.is_symlink() or receipt_path.is_symlink()):
            raise ValueError("SYMLINK_FILE")
        spec = read_spec(spec_path)
        digest = spec_digest(spec)
        raw_receipt = read_limited(receipt_path, 8192)
        receipt = json.loads(raw_receipt.decode("utf-8"))
        decision_raw = read_limited(choice_path, 4096)
        choices = _valid_decision(json.loads(decision_raw.decode("utf-8")), digest)
        if (not isinstance(receipt, dict)
                or receipt.get("schema") != "agentora.devboard.r1g.run.v1"
                or receipt.get("status") != "REVIEW_READY_NOT_AUTHORIZED"
                or receipt.get("spec_digest") != digest
                or receipt.get("artifact") != "artifact/index.html"
                or receipt.get("decision") != "design-decision.json"
                or receipt.get("decision_sha256") != hashlib.sha256(decision_raw).hexdigest()
                or receipt.get("model") != MODEL or receipt.get("choices") != choices
                or receipt.get("model_contribution") != "THREE_BOUNDED_ENUM_DECISIONS_ONLY"
                or receipt.get("html_verifier") != "independent-fixture-verifier-process"
                or receipt.get("design_verifier") != "independent-process-exact-design-contract-verifier"
                or receipt.get("eligible_for_merge") is not False
                or receipt.get("automatic_merge") is not False
                or receipt.get("repository_writes") != "NONE"):
            raise ValueError("RECEIPT_NOT_ELIGIBLE")
        sha = hashlib.sha256(read_limited(artifact, MAX_SIZE)).hexdigest()
        if receipt.get("artifact_sha256") != sha:
            raise ValueError("ARTIFACT_SHA_CHANGED")
        static = run_worker("r1b_verifier_worker.py",
                            [str(spec_path), str(artifact), sha], workspace)
        design = child("r1g_design_verifier.py",
                       [str(spec_path), str(choice_path), str(artifact), sha],
                       workspace, timeout=12)
        if (static.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or static.get("spec_digest") != digest
                or static.get("artifact_sha256") != sha
                or design.get("status") != "DESIGN_BINDING_PASS_SELF_REPORTED"
                or design.get("spec_digest") != digest
                or design.get("artifact_sha256") != sha
                or design.get("choices") != choices):
            raise ValueError("RECHECK_WORKER_REFUSED")
        if hashlib.sha256(read_limited(artifact, MAX_SIZE)).hexdigest() != sha:
            raise ValueError("ARTIFACT_TAMPERED_DURING_RECHECK")
        return {
            "status": "LOCAL_RECHECK_PASS_REVIEW_ONLY", "spec_digest": digest,
            "artifact_sha256": sha, "decision_sha256": hashlib.sha256(decision_raw).hexdigest(),
            "model": MODEL, "choices": choices,
            "model_contribution": "THREE_BOUNDED_ENUM_DECISIONS_ONLY",
            "eligible_for_merge": False, "automatic_merge": False,
        }
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {"status": "HELD", "reason": "DESIGN_RECHECK_REFUSED",
                "eligible_for_merge": False, "automatic_merge": False}
