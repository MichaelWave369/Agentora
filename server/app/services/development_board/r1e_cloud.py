"""R1-E GitHub-hosted, manual-only builder/verifier demo.

No token, repository writes, merge, deploy or scheduled execution. GitHub Actions
workflow_dispatch is the ONLY intended cloud entrypoint. The sample spec is a
committed, fixed, public fixture; the user cannot submit arbitrary source code.
Local files are self-reported observations, NOT independently signed attestations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .r1b_contract import frozen_bytes, read_spec, spec_digest
from .r1b_cli import run_pilot as fixed_pilot
from .r1f_cloud_theme import run_theme_pilot as model_pilot, recheck_theme as recheck_workspace
from .r1f_theme_worker import THEMES

ROOT = Path(__file__).resolve().parents[4]
SPEC_PATH = ROOT / "examples" / "development-board" / "r1b-fixture-spec.json"
MODES = frozenset(("fixture", "ollama_cpu"))
MAX_ARTIFACT_BYTES = 12 * 1024
ALLOWED_MODELS = {"ollama_cpu": "qwen3:0.6b"}


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def _held(mode: str, code: str, sha: str) -> dict[str, Any]:
    return {
        "schema": "agentora.devboard.r1e.cloud.v1",
        "status": "HELD",
        "reason": code,
        "mode": mode,
        "source_commit_sha_claim": sha,
        "qualification": "GITHUB_HOSTED_SELF_REPORTED_NOT_ATTESTED",
        "eligible_for_merge": False,
        "automatic_merge": False,
        "human_release_review_required": True,
        "github_writes": "NONE",
        "github_deploy": "NONE",
    }


def _read_file(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("INVALID_OR_SYMLINK_FILE")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("INVALID_FILE_SIZE")
    return data


def plan_cloud(mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError("UNKNOWN_CLOUD_MODE")
    spec = read_spec(SPEC_PATH)
    return {
        "schema": "agentora.devboard.r1e.plan.v1",
        "mode": mode,
        "spec": "examples/development-board/r1b-fixture-spec.json",
        "frozen_spec_sha256": spec_digest(spec),
        "trigger": "MANUAL_WORKFLOW_DISPATCH_ONLY",
        "builder": "FIXED_HTML_WORKER" if mode == "fixture" else "OLLAMA_THEME_CHOICE_AND_FIXED_SAFE_TEMPLATE",
        "verifier": "SEPARATE_LOCAL_STATIC_CHECK_PROCESS",
        "model_download": mode == "ollama_cpu",
        "environment": "EPHEMERAL_GITHUB_ACTIONS_RUNNER",
        "eligible_for_merge": False,
        "automatic_merge": False,
    }


def run_cloud(mode: str, output_dir: Path, *, head_sha: str = "",
              fixed_runner=None, model_runner=None, rechecker=None) -> dict[str, Any]:
    """Run a bounded fixed spec and only export an artifact on passing checks.

    Test seams are injectable without contacting any model in unit tests.
    Even a passing model proposal is exported as .html.txt, NOT opened/deployed.
    """
    if mode not in MODES:
        raise ValueError("UNKNOWN_CLOUD_MODE")
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("OUTPUT_DIRECTORY_MUST_EXIST_AND_NOT_BE_SYMLINK")
    if list(output_dir.iterdir()):
        raise ValueError("OUTPUT_DIRECTORY_MUST_BE_EMPTY")
    sha = head_sha if isinstance(head_sha, str) and len(head_sha) == 40 and all(
        c in "0123456789abcdef" for c in head_sha
    ) else "UNVERIFIED_SHA"
    spec = read_spec(SPEC_PATH)
    digest = spec_digest(spec)
    fixed_runner = fixed_runner or fixed_pilot
    model_runner = model_runner or model_pilot
    rechecker = rechecker or recheck_workspace
    result = _held(mode, "NOT_EXECUTED", sha)
    accepted: dict[str, Any] | None = None
    try:
        if mode == "fixture":
            observed = fixed_runner(SPEC_PATH, digest)
        else:
            observed = model_runner(
                SPEC_PATH, digest, model=ALLOWED_MODELS["ollama_cpu"], port=11434,
            )
        if not isinstance(observed, dict) or observed.get("status") != "REVIEW_READY_NOT_AUTHORIZED":
            result = _held(mode, "BUILDER_OR_VERIFIER_HELD", sha)
            if isinstance(observed, dict):
                source_reason = observed.get("reason")
                source_stage = observed.get("failed_stage")
                if (isinstance(source_reason, str) and 1 <= len(source_reason) <= 64
                        and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in source_reason)):
                    result["bounded_origin_reason"] = source_reason
                if source_stage in ("PRECHECK", "WORKSPACE", "MODEL_OR_TEMPLATE", "ARTIFACT", "INDEPENDENT_VERIFIER"):
                    result["origin_stage"] = source_stage
        elif (observed.get("spec_digest") != digest or
              observed.get("eligible_for_merge") is not False or
              observed.get("automatic_merge") is not False or
              observed.get("artifact") != "artifact/index.html" or
              observed.get("repository_writes", "NONE") != "NONE"):
            result = _held(mode, "BOUNDARY_OR_SPEC_MISMATCH", sha)
        elif mode == "ollama_cpu" and (observed.get("model") != ALLOWED_MODELS["ollama_cpu"]
                                       or observed.get("model_contribution") != "BOUNDED_THEME_ENUM_ONLY"
                                       or observed.get("theme") not in THEMES):
            result = _held(mode, "MODEL_IDENTITY_OR_OUTPUT_UNVERIFIED", sha)
        else:
            location = Path(observed["workspace"])
            if location.is_symlink() or not location.is_dir():
                raise ValueError("INVALID_PILOT_WORKSPACE")
            artifact = location / "artifact" / "index.html"
            raw = _read_file(artifact, MAX_ARTIFACT_BYTES)
            calculated_sha = hashlib.sha256(raw).hexdigest()
            if calculated_sha != observed.get("artifact_sha256"):
                result = _held(mode, "ARTIFACT_HASH_CHANGED", sha)
            else:
                if mode == "ollama_cpu":
                    rechecked = rechecker(location)
                    if (not isinstance(rechecked, dict)
                            or rechecked.get("status") != "LOCAL_RECHECK_PASS_REVIEW_ONLY"
                            or rechecked.get("spec_digest") != digest
                            or rechecked.get("artifact_sha256") != calculated_sha
                            or rechecked.get("eligible_for_merge") is not False):
                        result = _held(mode, "INDEPENDENT_RECHECK_HELD", sha)
                    else:
                        accepted = {"sha256": calculated_sha, "raw": raw}
                else:
                    accepted = {"sha256": calculated_sha, "raw": raw}
                if accepted is not None:
                    # A passing static report is not an external witness or license to ship.
                    result = {
                        "schema": "agentora.devboard.r1e.cloud.v1",
                        "status": "STATIC_REVIEW_READY_NOT_AUTHORIZED",
                        "mode": mode,
                        "source_commit_sha_claim": sha,
                        "frozen_spec_digest": digest,
                        "artifact_sha256": calculated_sha,
                        "artifact_export": (
                            "index.html" if mode == "fixture"
                            else "untrusted-model-proposal.html.txt"
                        ),
                        "model": ALLOWED_MODELS["ollama_cpu"] if mode == "ollama_cpu" else None,
                        "model_contribution": "BOUNDED_THEME_ENUM_ONLY" if mode == "ollama_cpu" else "NONE",
                        "deterministic_markup_builder": True,
                        "theme": observed.get("theme") if mode == "ollama_cpu" else None,
                        "qualification": "GITHUB_HOSTED_SELF_REPORTED_NOT_ATTESTED",
                        "manual_trigger_claim": "WORKFLOW_DISPATCH",
                        "human_visual_review": "NOT_PERFORMED",
                        "code_brown_first_use_test": "NOT_PERFORMED",
                        "eligible_for_merge": False,
                        "automatic_merge": False,
                        "human_release_review_required": True,
                        "github_writes": "NONE",
                        "github_deploy": "NONE",
                    }
    except (OSError, ValueError, TypeError, KeyError):
        result = _held(mode, "PROCESS_OR_EVIDENCE_ERROR", sha)

    # Always produce a small refusal/success report, but never publish held
    # model HTML or a claimed passing receipt on incomplete verification.
    _write_new(output_dir / "cloud-report.json",
               (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    if accepted is not None and result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED":
        _write_new(output_dir / result["artifact_export"], accepted["raw"])
        _write_new(output_dir / "frozen-spec.json", frozen_bytes(spec) + b"\n")
    return result


def main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Agentora R1-E hosted read-only demonstration")
    sub = parser.add_subparsers(dest="command", required=True)
    preview = sub.add_parser("plan", help="Describe fixed, committed cloud task")
    preview.add_argument("--mode", required=True, choices=sorted(MODES))
    execution = sub.add_parser("run", help="Run ONLY from manual GitHub Actions event")
    execution.add_argument("--mode", required=True, choices=sorted(MODES))
    execution.add_argument("--output-dir", type=Path, required=True)
    opts = parser.parse_args(args)
    if opts.command == "plan":
        print(json.dumps(plan_cloud(opts.mode), indent=2, sort_keys=True))
        return 0
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or os.environ.get("GITHUB_ACTIONS") != "true":
        print(json.dumps(_held(opts.mode, "MANUAL_GITHUB_ACTIONS_DISPATCH_REQUIRED", "UNVERIFIED_SHA")))
        return 2
    try:
        result = run_cloud(opts.mode, opts.output_dir, head_sha=os.environ.get("GITHUB_SHA", ""))
    except (OSError, ValueError):
        print(json.dumps(_held(opts.mode, "INVALID_OUTPUT_DIRECTORY", "UNVERIFIED_SHA")))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
