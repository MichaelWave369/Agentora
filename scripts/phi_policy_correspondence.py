"""R0.4: compare Lean oracle against executable Agentora policy code.

This performs exhaustive 16-input/3-evidence-tier differential testing of
a *read-only advisory* policy adapter in the existing DevLoop policy module.
The Python implementation is NOT Lean-verified and is NOT consulted by the
privileged merge function. No action authority is issued.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import subprocess

from devloop_r2_policy import correspondence_policy_snapshot

SCHEMA = "agentora.phi.policy-correspondence.v0.4"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
GATE = re.compile(r"G\|([01]{4})\|([01])\Z")
EVIDENCE = re.compile(r"E\|(declared|githubCorroborated|formallyCheckedModel)\|([01]{4})\Z")
LEVELS = ("declared", "githubCorroborated", "formallyCheckedModel")
SOURCE_PATHS = (
    "formal/phi-evidence/PhiEvidence.lean",
    "formal/phi-evidence/PolicyOracle.lean",
    "formal/phi-evidence/lean-toolchain",
    "formal/phi-evidence/lakefile.toml",
    "formal/phi-evidence/lake-manifest.json",
    "scripts/devloop_r2_policy.py",
    "scripts/phi_policy_correspondence.py",
)
EXPECTED_TOOLCHAIN = "leanprover/lean4:v4.35.0"


class CorrespondenceHeld(ValueError):
    """No source-to-model correspondence certificate issued."""


def need(ok, reason):
    if not ok:
        raise CorrespondenceHeld(reason)


def parse_oracle(stdout):
    """Exactly 16 unique gates and 3 evidence tiers; no extra output."""
    need(type(stdout) is str and 0 < len(stdout) < 4096, "LEAN_ORACLE_OUTPUT_BOUNDS")
    lines = stdout.splitlines()
    need(len(lines) == 19, "LEAN_ORACLE_LINE_COUNT")
    gates, evidence = {}, {}
    for line in lines:
        match = GATE.fullmatch(line)
        if match:
            bits, expected = match.groups()
            need(bits not in gates, "LEAN_ORACLE_DUPLICATE_GATE")
            gates[bits] = expected == "1"
            continue
        match = EVIDENCE.fullmatch(line)
        if match:
            name, flags = match.groups()
            need(name not in evidence, "LEAN_ORACLE_DUPLICATE_EVIDENCE")
            evidence[name] = flags
            continue
        raise CorrespondenceHeld("LEAN_ORACLE_UNRECOGNIZED_LINE")
    expected_inputs = {"".join(bits) for bits in itertools.product("01", repeat=4)}
    need(set(gates) == expected_inputs and set(evidence) == set(LEVELS),
         "LEAN_ORACLE_COVERAGE_MISSING")
    return gates, evidence


def compare(oracle, *, implementation=correspondence_policy_snapshot):
    """Fail closed on the first divergence from Lean's evaluated definitions."""
    gates, evidence = parse_oracle(oracle)
    count = 0
    for bits in sorted(gates):
        args = tuple(bit == "1" for bit in bits)
        for tier in LEVELS:
            try:
                result = implementation(*args, tier)
            except Exception as exc:
                raise CorrespondenceHeld("PYTHON_MODEL_EXECUTION_HELD") from exc
            need(type(result) is dict and
                 set(result) == {
                     "model_gate_conjunction", "evidence_authority",
                     "action_authorized", "review_only"},
                 "PYTHON_POLICY_RESULT_SHAPE_DRIFT")
            need(type(result["model_gate_conjunction"]) is bool and
                 result["model_gate_conjunction"] is gates[bits],
                 "PYTHON_GATE_DIVERGES_FROM_LEAN")
            actual_auth = result["evidence_authority"]
            need(type(actual_auth) is dict and
                 set(actual_auth) == {
                     "code_write", "worker_dispatch", "merge", "deploy"} and
                 all(type(v) is bool for v in actual_auth.values()),
                 "PYTHON_AUTHORITY_RESULT_SHAPE_DRIFT")
            actual_bits = "".join("1" if actual_auth[k] else "0"
                for k in ("code_write", "worker_dispatch", "merge", "deploy"))
            need(actual_bits == evidence[tier],
                 "PYTHON_AUTHORITY_DIVERGES_FROM_LEAN")
            need(result["action_authorized"] is False and
                 result["review_only"] is True,
                 "PYTHON_POLICY_PRIVILEGE_ESCALATION")
            count += 1
    return count


def checked(cmd, cwd, runner):
    try:
        result = runner(cmd, cwd=cwd, capture_output=True, text=True,
                        timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CorrespondenceHeld("LEAN_OR_GIT_EXECUTION_FAILED") from exc
    need(result.returncode == 0 and type(result.stdout) is str and
         len(result.stdout) <= 65536,
         "LEAN_OR_GIT_PROCESS_FAILED")
    return result.stdout


def build_receipt(root, expected_sha, *, runner=subprocess.run,
                  implementation=correspondence_policy_snapshot):
    need(type(expected_sha) is str and SHA40.fullmatch(expected_sha) is not None,
         "SOURCE_SHA_INVALID")
    root = Path(root).resolve(strict=True)
    hashes = {}
    for relative in SOURCE_PATHS:
        path = root / relative
        need(not path.is_symlink() and path.is_file(),
             "SOURCE_FILE_MISSING_OR_SYMLINK")
        raw = path.read_bytes()
        need(0 < len(raw) <= 250_000, "SOURCE_FILE_BOUNDS")
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    need((root / "formal/phi-evidence/lean-toolchain").read_text(
        encoding="utf-8").strip() == EXPECTED_TOOLCHAIN,
         "LEAN_TOOLCHAIN_NOT_PINNED")
    actual_sha = checked(["git", "rev-parse", "HEAD"], root, runner).strip()
    need(actual_sha == expected_sha, "CHECKOUT_HEAD_SHA_DRIFT")
    directory = root / "formal/phi-evidence"
    version = checked(["lean", "--version"], directory, runner).strip()
    need(version.startswith("Lean (version 4.35.0"),
         "LEAN_BINARY_VERSION_DRIFT")
    # The workflow runs R0.3 kernel checks before this oracle evaluation.
    # The model is already built by the Lean step, so import its olean.
    output = checked(["lake", "env", "lean", "--run", "PolicyOracle.lean"],
                     directory, runner)
    comparisons = compare(output, implementation=implementation)
    return {
        "schema": SCHEMA,
        "state": "LEAN_PYTHON_FINITE_CORRESPONDENCE_REVIEW_ONLY",
        "checked_commit_sha": actual_sha,
        "source_sha256": hashes,
        "lean_toolchain": EXPECTED_TOOLCHAIN,
        "lean_version_observed": version,
        "oracle_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "gate_vectors_checked": 16,
        "evidence_tiers_checked": 3,
        "comparisons_executed": comparisons,
        "actual_privileged_merge_function_exercised": False,
        "python_implementation_formally_proven": False,
        "compiler_or_machine_code_verified": False,
        "operator_identity_authenticated": False,
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
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        report = build_receipt(args.root, args.expected_sha)
        dest = args.output.resolve()
        root = args.root.resolve()
        need(dest.suffix == ".json" and root not in dest.parents and
             dest != root and not dest.is_symlink() and not dest.exists(),
             "RECEIPT_OUTPUT_NOT_SAFE")
        dest.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    except (CorrespondenceHeld, UnicodeError, OSError, ValueError) as exc:
        p.exit(2, "PHI POLICY CORRESPONDENCE HELD: " + str(exc) + "\n")
    print("PHI POLICY CORRESPONDENCE REVIEW_ONLY: " + str(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
