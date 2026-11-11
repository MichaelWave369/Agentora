"""R0.3: execute the pinned Lean model checker and emit a bounded SHA receipt.

Only proves theorems of the local abstract policy model. A successful Lean
check DOES NOT prove Python, GitHub, generated machine code, model inference
or real-world action authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SCHEMA = "agentora.phi.proof-model.v0.3"
TOOLCHAIN = "leanprover/lean4:v4.35.0"
SOURCE_FILES = (
    "formal/phi-evidence/PhiEvidence.lean",
    "formal/phi-evidence/lakefile.toml",
    "formal/phi-evidence/lean-toolchain",
    "scripts/phi_evidence_wire.py",
    "scripts/phi_evidence_live.py",
)
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
FORBIDDEN = re.compile(r"\b(?:sorry|admit|axiom|unsafe|native_decide)\b")
EXPECTED_CHECK = "Lean (version 4.35.0"


class ProofHeld(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise ProofHeld(reason)


def run_checked(cmd, *, cwd, runner=subprocess.run):
    try:
        result = runner(cmd, cwd=cwd, capture_output=True, text=True,
                        timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProofHeld("CHECKER_EXECUTION_FAILED") from exc
    need(result.returncode == 0, "CHECKER_RETURNED_NONZERO")
    need(type(result.stdout) is str and len(result.stdout) <= 262144,
         "CHECKER_OUTPUT_INVALID")
    return result.stdout


def build_receipt(root: Path, expected_sha: str, *, runner=subprocess.run) -> dict:
    root = root.resolve(strict=True)
    need(type(expected_sha) is str and SHA40.fullmatch(expected_sha) is not None,
         "EXPECTED_GIT_SHA_INVALID")
    files = {}
    for relative in SOURCE_FILES:
        path = root / relative
        need(not path.is_symlink() and path.is_file(), "PROOF_SOURCE_MISSING_OR_SYMLINK")
        raw = path.read_bytes()
        need(0 < len(raw) <= 250_000, "PROOF_SOURCE_SIZE_INVALID")
        files[relative] = hashlib.sha256(raw).hexdigest()

    proof = (root / SOURCE_FILES[0]).read_text(encoding="utf-8")
    need(FORBIDDEN.search(proof) is None, "UNTRUSTED_PROOF_ESCAPE_TOKEN")
    need((root / "formal/phi-evidence/lean-toolchain").read_text(
        encoding="utf-8").strip() == TOOLCHAIN, "TOOLCHAIN_NOT_PINNED")
    actual_sha = run_checked(["git", "rev-parse", "HEAD"], cwd=root,
                             runner=runner).strip()
    need(actual_sha == expected_sha, "CHECKOUT_SHA_NOT_EXPECTED")
    directory = root / "formal/phi-evidence"
    version = run_checked(["lean", "--version"], cwd=directory,
                          runner=runner).strip()
    need(version.startswith(EXPECTED_CHECK), "LEAN_VERSION_NOT_EXPECTED")
    run_checked(["lake", "build", "--wfail"], cwd=directory, runner=runner)
    run_checked(["lake", "env", "lean", "-DwarningAsError=true",
                 "PhiEvidence.lean"], cwd=directory, runner=runner)
    # The checker proved the abstract Lean model, not the referenced Python
    # implementation. File hashes bind this receipt to the observed snapshot.
    return {
        "schema": SCHEMA,
        "state": "LEAN_ABSTRACT_MODEL_CHECKED_REVIEW_ONLY",
        "checked_commit_sha": actual_sha,
        "lean_toolchain": TOOLCHAIN,
        "lean_version_observed": version,
        "file_sha256": files,
        "proof_scope": "ABSTRACT_POLICY_MODEL_ONLY",
        "source_code_behavior_proven": False,
        "compiled_machine_code_proven": False,
        "github_metadata_independently_authenticated": False,
        "proof_model_kernel_checked_in_this_process": True,
        "operator_policy_auto_approved": False,
        "model_routing_activated": False,
        "code_write_authorized": False,
        "worker_dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--expected-sha", default=os.environ.get("GITHUB_SHA"))
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        receipt = build_receipt(args.root, args.expected_sha)
        destination = args.output.resolve()
        need(destination.suffix == ".json", "RECEIPT_OUTPUT_TYPE_INVALID")
        # Never write proof receipts into the tracked repository checkout.
        root = args.root.resolve()
        need(root not in destination.parents and destination != root,
             "RECEIPT_MUST_LIVE_OUTSIDE_REPO")
        need(not destination.is_symlink() and not destination.exists(),
             "RECEIPT_OUTPUT_ALREADY_EXISTS")
        destination.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8")
    except (ProofHeld, OSError, UnicodeError, ValueError) as exc:
        p.exit(2, "PHI FORMAL MODEL HELD: " + str(exc) + "\n")
    print("PHI PROOF MODEL CHECKED_REVIEW_ONLY: " + str(destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
