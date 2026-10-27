"""R1-C operator-only local Ollama proposal + distinct static verifier processes.

An explicit CLI run sends a frozen declarative spec to local Ollama, saves
untrusted HTML in a disposable workspace, independently verifies it, and
withholds any release authority. This is NOT PhiBot delegation or a sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from .r1b_contract import frozen_bytes, read_spec, spec_digest
from .r1b_cli import _worker_env, run_worker as verify_worker
from .r1c_model_worker import checked_model, checked_port

HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIRECTORY = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 110
MAX_OUTPUT = 16384
MAX_ARTIFACT = 12 * 1024


def held(reason: str, workspace: str | None = None) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1c.run.v1",
        "status": "HELD",
        "reason": reason,
        "workspace": workspace,
        "eligible_for_merge": False,
        "automatic_merge": False,
        "human_review_required": True,
        "source_provenance": "LOCAL_SELF_REPORTED_UNATTESTED",
        "role_identity_authenticated": False,
        "repository_writes": "NONE",
    }


def plan(spec_path: Path, model: str = "qwen3.5:9b", port: int = 11434) -> dict[str, Any]:
    spec = read_spec(spec_path)
    return {
        "schema": "agentora.devboard.r1c.plan.v1",
        "mode": "LOCAL_MODEL_UNTRUSTED_STATIC_HTML_ONLY",
        "frozen_spec_digest": spec_digest(spec),
        "model": checked_model(model),
        "ollama_port": checked_port(port),
        "network_target": "127.0.0.1 ONLY (during a separately approved run)",
        "workflows": ["Ollama proposal worker", "independent static verifier"],
        "output": "new scratch/artifact/index.html only",
        "eligible_for_merge": False,
        "automatic_merge": False,
    }


def model_worker(spec: Path, artifact_dir: Path, workspace: Path,
                 model: str, port: int) -> dict[str, Any]:
    try:
        process = subprocess.run(
            [sys.executable, "-S", "-B", str(DIRECTORY / "r1c_model_worker.py"),
             str(spec), str(artifact_dir), model, str(port)],
            cwd=str(workspace),
            env=_worker_env(),
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "ERROR", "reason": "MODEL_WORKER_UNAVAILABLE_OR_TIMED_OUT"}
    if process.returncode != 0 or len(process.stdout) > MAX_OUTPUT:
        return {"status": "ERROR", "reason": "MODEL_WORKER_FAILED_OR_OUTPUT_INVALID"}
    try:
        result = json.loads(process.stdout)
    except (TypeError, ValueError):
        return {"status": "ERROR", "reason": "MODEL_WORKER_INVALID_JSON"}
    return result if isinstance(result, dict) else {"status": "ERROR", "reason": "MODEL_WORKER_INVALID_RESULT"}


def run_pilot(spec_path: Path, approved_digest: str, *, model: str = "qwen3.5:9b",
              port: int = 11434, scratch_root: Path | None = None) -> dict[str, Any]:
    try:
        spec = read_spec(spec_path)
        approved_model = checked_model(model)
        approved_port = checked_port(port)
    except (OSError, ValueError, TypeError):
        return held("INVALID_SPEC_MODEL_OR_PORT")
    digest = spec_digest(spec)
    if not isinstance(approved_digest, str) or not HEX64.fullmatch(approved_digest):
        return held("EXACT_SPEC_ACK_REQUIRED")
    if approved_digest != digest:
        return held("SPEC_CHANGED_SINCE_OPERATOR_ACK")
    # Child gets only a minimal environment. Still NOT isolated from the local user.
    try:
        workspace = Path(tempfile.mkdtemp(
            prefix="agentora-devboard-r1c-",
            dir=str(scratch_root) if scratch_root is not None else None,
        ))
    except OSError:
        return held("SCRATCH_WORKSPACE_UNAVAILABLE")
    location = str(workspace)
    try:
        artifact_dir = workspace / "artifact"
        artifact_dir.mkdir()
        frozen_path = workspace / "frozen-spec.json"
        frozen_path.write_bytes(frozen_bytes(spec))
        proposal = model_worker(frozen_path, artifact_dir, workspace,
                                approved_model, approved_port)
        if (proposal.get("status") != "UNTRUSTED_PROPOSAL_SAVED"
                or proposal.get("worker") != "local-ollama-html-proposal-process"
                or proposal.get("model") != approved_model
                or proposal.get("spec_digest") != digest
                or proposal.get("artifact") != "index.html"):
            return held("MODEL_PROPOSAL_FAILED_OR_CHANGED_SCOPE", location)
        artifact = artifact_dir / "index.html"
        if artifact.is_symlink() or not artifact.is_file():
            return held("MODEL_ARTIFACT_NOT_REGULAR_FILE", location)
        with artifact.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT + 1)
        if not 0 < len(raw) <= MAX_ARTIFACT:
            return held("MODEL_ARTIFACT_INVALID_SIZE", location)
        sha = hashlib.sha256(raw).hexdigest()
        if proposal.get("artifact_sha256") != sha:
            return held("MODEL_PROPOSAL_SHA_MISMATCH", location)
        verdict = verify_worker(
            "r1b_verifier_worker.py",
            [str(frozen_path), str(artifact), sha], workspace,
        )
        if (verdict.get("status") != "STATIC_CHECKS_PASS_SELF_REPORTED"
                or verdict.get("worker") != "independent-fixture-verifier-process"
                or verdict.get("spec_digest") != digest
                or verdict.get("artifact_sha256") != sha
                or verdict.get("artifact") != "index.html"):
            return held("STATIC_VERIFIER_REFUSED_UNTRUSTED_PROPOSAL", location)
        if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != sha:
            return held("MODEL_ARTIFACT_CHANGED_AFTER_VERIFICATION", location)
        receipt = {
            "schema": "agentora.devboard.r1c.run.v1",
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "workspace": location,
            "spec_digest": digest,
            "artifact_sha256": sha,
            "artifact": "artifact/index.html",
            "model": approved_model,
            "model_output": "UNTRUSTED_STATIC_HTML_PROPOSAL",
            "model_worker": "local-ollama-html-proposal-process",
            "static_verifier": "independent-fixture-verifier-process",
            "static_checks": verdict.get("checks", []),
            "role_separation": "TWO_LOCAL_PROCESSES_NOT_SECURITY_ISOLATION",
            "source_provenance": "LOCAL_SELF_REPORTED_UNATTESTED",
            "role_identity_authenticated": False,
            "human_review_required": True,
            "eligible_for_merge": False,
            "automatic_merge": False,
            "repository_writes": "NONE",
            "network_scope": "LOOPBACK_OLLAMA_ONLY",
        }
        with (workspace / "review-receipt.json").open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
        return receipt
    except (OSError, TypeError, ValueError):
        return held("UNVERIFIED_OR_INCOMPLETE_LOCAL_WORKSPACE", location)


def main(args: list[str]) -> int:
    cli = argparse.ArgumentParser(description="R1-C opt-in local model HTML proposal trial")
    modes = cli.add_subparsers(dest="operation", required=True)
    p = modes.add_parser("plan", help="Read only: approve exact specification first")
    p.add_argument("spec", type=Path)
    r = modes.add_parser("run", help="Opt-in local Ollama call and scratch artifact only")
    r.add_argument("spec", type=Path)
    r.add_argument("--approve-spec-digest", required=True)
    r.add_argument("--i-approve-local-model", action="store_true")
    for mode in (p, r):
        mode.add_argument("--model", default="qwen3.5:9b")
        mode.add_argument("--ollama-port", type=int, default=11434)
    options = cli.parse_args(args)
    if options.operation == "run" and not options.i_approve_local_model:
        output = held("LOCAL_MODEL_APPROVAL_FLAG_REQUIRED")
    elif options.operation == "plan":
        try:
            output = plan(options.spec, options.model, options.ollama_port)
        except (OSError, ValueError, TypeError):
            output = held("INVALID_SPEC_MODEL_OR_PORT")
    else:
        output = run_pilot(
            options.spec, options.approve_spec_digest,
            model=options.model, port=options.ollama_port,
        )
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if output.get("status") == "REVIEW_READY_NOT_AUTHORIZED" or (
        output.get("schema") == "agentora.devboard.r1c.plan.v1"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
