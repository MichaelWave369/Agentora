"""R1-B operator-only scratch build + separate-process verification coordinator.

R1-B proves a real *deterministic* local builder/verifier handoff. It does not
invoke an AI model, use GitPorch/PhiBot credentials or alter GitHub repositories.
Subprocess separation is not OS sandbox isolation or independent attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from .r1b_contract import frozen_bytes, read_spec, spec_digest

SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIRECTORY = Path(__file__).resolve().parent
MAX_CHILD_OUTPUT = 16 * 1024
TIMEOUT_SECONDS = 10


def _held(reason: str, workspace: str | None = None) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1b.run.v1",
        "status": "HELD",
        "reason": reason,
        "workspace": workspace,
        "eligible_for_merge": False,
        "automatic_merge": False,
        "role_identity_authenticated": False,
        "source_provenance": "LOCAL_SELF_REPORTED_UNATTESTED",
    }


def _worker_env() -> dict[str, str]:
    # Pass only minimal OS/runtime needs, never inherited GitHub or Ollama secrets.
    selected = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME")
    env = {key: os.environ[key] for key in selected if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_worker(script: str, args: list[str], workspace: Path) -> dict[str, Any]:
    if script not in ("r1b_builder_worker.py", "r1b_verifier_worker.py"):
        return {"status": "ERROR", "reason": "UNKNOWN_WORKER"}
    try:
        child = subprocess.run(
            [sys.executable, "-S", "-B", str(DIRECTORY / script), *args],
            cwd=str(workspace), env=_worker_env(), capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "ERROR", "reason": "WORKER_UNAVAILABLE_OR_TIMED_OUT"}
    if child.returncode != 0 or len(child.stdout) > MAX_CHILD_OUTPUT:
        return {"status": "ERROR", "reason": "WORKER_FAILED_OR_OUTPUT_INVALID"}
    try:
        result = json.loads(child.stdout)
    except (TypeError, ValueError):
        return {"status": "ERROR", "reason": "WORKER_INVALID_JSON"}
    return result if isinstance(result, dict) else {"status": "ERROR", "reason": "WORKER_INVALID_RESULT"}


def plan(spec_path: Path) -> dict[str, Any]:
    spec = read_spec(spec_path)
    return {
        "schema": "agentora.devboard.r1b.plan.v1",
        "mode": "FIXED_FIXTURE_ONLY",
        "frozen_spec_digest": spec_digest(spec),
        "title": spec["title"],
        "output": "new scratch/index.html only",
        "workers": ["fixed-fixture-builder-process", "independent-fixture-verifier-process"],
        "human_review_required": True,
        "model_invocation": False,
        "eligible_for_merge": False,
        "automatic_merge": False,
    }


def run_pilot(spec_path: Path, approved_digest: str, *,
              scratch_root: Path | None = None) -> dict[str, Any]:
    spec = read_spec(spec_path)
    frozen = frozen_bytes(spec)
    digest = hashlib.sha256(frozen).hexdigest()
    if not isinstance(approved_digest, str) or not SHA256.fullmatch(approved_digest):
        return _held("APPROVAL_DIGEST_REQUIRED")
    if approved_digest != digest:
        return _held("SPEC_DIGEST_DOES_NOT_MATCH_OPERATOR_ACK")
    # Never use the caller-supplied spec path as the output destination.
    workspace = Path(tempfile.mkdtemp(
        prefix="agentora-devboard-r1b-",
        dir=str(scratch_root) if scratch_root is not None else None,
    ))
    location = str(workspace)
    try:
        artifact_dir = workspace / "artifact"
        artifact_dir.mkdir()
        frozen_path = workspace / "frozen-spec.json"
        with frozen_path.open("xb") as stream:
            stream.write(frozen)

        built = run_worker(
            "r1b_builder_worker.py", [str(frozen_path), str(artifact_dir)], workspace
        )
        target = artifact_dir / "index.html"
        if (built.get("status") != "BUILT_SELF_REPORTED"
                or built.get("spec_digest") != digest
                or built.get("artifact") != "index.html"
                or built.get("worker") != "fixed-fixture-builder-process"):
            return _held("BUILDER_FAILED_OR_CHANGED_SPEC", location)
        if target.is_symlink() or not target.is_file():
            return _held("ARTIFACT_NOT_REGULAR_FILE", location)
        raw = target.read_bytes()
        if not 0 < len(raw) <= 12 * 1024:
            return _held("ARTIFACT_SIZE_INVALID", location)
        artifact_digest = hashlib.sha256(raw).hexdigest()
        if built.get("artifact_sha256") != artifact_digest:
            return _held("BUILDER_SHA_MISMATCH", location)

        verified = run_worker(
            "r1b_verifier_worker.py",
            [str(frozen_path), str(target), artifact_digest], workspace,
        )
        # Reread after verification to reject changes during handoff.
        final_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if final_digest != artifact_digest:
            return _held("ARTIFACT_CHANGED_DURING_VERIFICATION", location)
        if (verified.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or verified.get("worker") != "independent-fixture-verifier-process"
                or verified.get("spec_digest") != digest
                or verified.get("artifact_sha256") != artifact_digest
                or verified.get("artifact") != "index.html"):
            return _held("INDEPENDENT_VERIFIER_NOT_PASSING", location)
        receipt = {
            "schema": "agentora.devboard.r1b.run.v1",
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "role_separation": "DISTINCT_OS_PROCESSES_NOT_SECURITY_ISOLATION",
            "source_provenance": "LOCAL_SELF_REPORTED_UNATTESTED",
            "spec_digest": digest,
            "artifact_sha256": artifact_digest,
            "artifact": "artifact/index.html",
            "builder": built["worker"],
            "verifier": verified["worker"],
            "observed_static_checks": verified.get("checks", []),
            "workspace": location,
            "human_review_required": True,
            "eligible_for_merge": False,
            "automatic_merge": False,
            "role_identity_authenticated": False,
            "git_actions": "NONE",
            "model_invocation": False,
        }
        with (workspace / "review-receipt.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write("\n")
        return receipt
    except (OSError, ValueError, TypeError):
        return _held("LOCAL_WORKSPACE_OR_RECEIPT_ERROR", location)


def main(args: list[str]) -> int:
    import argparse

    cli = argparse.ArgumentParser(description="Agentora R1-B scratch builder/verifier pilot")
    choices = cli.add_subparsers(dest="operation", required=True)
    p = choices.add_parser("plan", help="Read-only: print canonical spec digest")
    p.add_argument("spec", type=Path)
    r = choices.add_parser("run", help="Explicit operator approval: write a scratch fixture")
    r.add_argument("spec", type=Path)
    r.add_argument("--approve-spec-digest", required=True)
    r.add_argument("--i-approve-local-fixture", action="store_true")
    options = cli.parse_args(args)
    try:
        if options.operation == "plan":
            outcome = plan(options.spec)
        elif not options.i_approve_local_fixture:
            outcome = _held("EXPLICIT_LOCAL_FIXTURE_APPROVAL_REQUIRED")
        else:
            outcome = run_pilot(options.spec, options.approve_spec_digest)
    except (OSError, ValueError):
        outcome = _held("INVALID_OR_UNREADABLE_SPEC")
    print(json.dumps(outcome, sort_keys=True, indent=2))
    return 0 if outcome.get("status") in (
        "REVIEW_READY_NOT_AUTHORIZED", "agentora.devboard.r1b.plan.v1"
    ) or outcome.get("schema") == "agentora.devboard.r1b.plan.v1" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
