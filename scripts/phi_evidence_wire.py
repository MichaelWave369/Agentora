"""Phi Evidence Wire R0.1: correlate existing evidence without granting authority.

Read-only bridge for GMED v1, Agentora Fleet R14, and optional PhiStream
CLAVIS R0.3 public qualification *summary*. No model calls, repository writes,
proof claims, independent source authentication, or merge authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "agentora.phi.evidence-wire.v0.1"
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}\Z")
MAX_INPUT_BYTES = 131072
R14_STATES = {
    "EVIDENCE_LINKED_PENDING_OWNER_REVIEW": False,
    "OWNER_REVIEW_ACKNOWLEDGED_NO_APPROVAL": True,
}


class EvidenceHeld(ValueError):
    """Untrusted, incomplete or uncorrelated evidence."""


def need(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceHeld(reason)


def digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_public_summary(path: Path) -> dict:
    need(not path.is_symlink(), "SYMLINK_INPUT_HELD")
    need(path.is_file(), "MISSING_OR_NONFILE_INPUT")
    need(0 < path.stat().st_size <= MAX_INPUT_BYTES, "INPUT_SIZE_HELD")
    raw = path.read_bytes()
    need(0 < len(raw) <= MAX_INPUT_BYTES, "INPUT_SIZE_CHANGED")
    try:
        value = json.loads(raw.decode("utf-8"),
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise EvidenceHeld("INVALID_JSON_INPUT") from exc
    need(type(value) is dict, "INPUT_NOT_OBJECT")
    return value


def gmed_observation(receipt: dict, sha: str) -> dict:
    """Check the *declared* GMED v1 summary and its own check-row arithmetic.

    GMED has to be run separately against GitHub; a copied JSON file is
    neither trusted GitHub evidence nor an independent verifier.
    """
    need(receipt.get("schema") == "gmed-report:v1" and
         receipt.get("state") == "GMED" and
         receipt.get("merged") is True and
         receipt.get("sha") == sha, "GMED_IDENTITY_OR_STATE_HELD")
    counts, checks = receipt.get("counts"), receipt.get("checks")
    need(type(counts) is dict and type(checks) is list and
         0 < len(checks) <= 1000, "GMED_CHECKS_MISSING")
    expected = dict(total=len(checks), passed=0, accepted=0,
                    failed=0, pending=0, unknown=0)
    for row in checks:
        need(type(row) is dict, "GMED_CHECK_ROW_INVALID")
        kind, grade = row.get("kind"), row.get("grade")
        if kind == "check":
            need(row.get("status") == "completed" and grade == "good" and
                 row.get("conclusion") in ("success", "neutral", "skipped"),
                 "GMED_CHECK_NOT_PASSING")
            expected["accepted"] += 1
            expected["passed"] += int(row["conclusion"] == "success")
        elif kind == "status":
            need(row.get("status") == "success" and grade == "good",
                 "GMED_COMMIT_STATUS_NOT_PASSING")
            expected["accepted"] += 1
            expected["passed"] += 1
        else:
            raise EvidenceHeld("GMED_CHECK_KIND_INVALID")
    need(counts == expected and expected["passed"] > 0,
         "GMED_CHECK_ARITHMETIC_HELD")
    return {"schema": "gmed-report:v1", "status": "DECLARED_GMED_ONLY",
            "receipt_sha256": digest(receipt)}


def r14_observation(receipt: dict, repo: str, sha: str) -> dict:
    need(receipt.get("schema") == "agentora.fleet.r14.evidence-handoff.v1"
         and receipt.get("target_repository") == repo
         and receipt.get("source_sha") == sha
         and receipt.get("state") in R14_STATES, "R14_SOURCE_IDENTITY_HELD")
    state = receipt["state"]
    need(receipt.get("owner_acknowledged") is R14_STATES[state] and
         receipt.get("command") ==
            ("acknowledge" if R14_STATES[state] else "link"),
         "R14_STATE_TRANSITION_HELD")
    need(type(receipt.get("mission_issue")) is int and
         receipt["mission_issue"] > 0 and
         type(receipt.get("audit_run_id")) is int and
         receipt["audit_run_id"] > 0 and
         type(receipt.get("qa_run_id")) is int and
         receipt["qa_run_id"] > 0 and
         receipt["audit_run_id"] != receipt["qa_run_id"], "R14_RUN_BINDING_HELD")
    for field in ("issue_sha256", "audit_artifact_sha256",
                  "qa_artifact_sha256"):
        need(type(receipt.get(field)) is str and
             SHA64.fullmatch(receipt[field]) is not None,
             "R14_DIGEST_BINDING_HELD")
    need(receipt.get("code_write_blocked") is True and
         all(receipt.get(field) is False for field in
             ("worker_execution_authorized", "independent_human_qa_complete",
              "merge_authorized", "deployment_authorized")),
         "R14_PRIVILEGE_ESCALATION_HELD")
    return {"schema": "agentora.fleet.r14.evidence-handoff.v1",
            "status": state, "receipt_sha256": digest(receipt)}


def clavis_observation(receipt: dict) -> dict:
    """Only accept the *public summary*, never private datasets/packs/keys."""
    need(receipt.get("schema") == "phistream.clavis.qualification-review.v0.3"
         and type(receipt.get("status")) is str
         and receipt["status"].startswith(("HELD", "SCREENED_FOR_")),
         "CLAVIS_RESEARCH_SCHEMA_HELD")
    need(all(receipt.get(field) is False for field in
             ("quality_proven", "routing_activated", "deployment_authorized",
              "private_prompts_answers_or_mappings_exported")),
         "CLAVIS_SCOPE_OR_PRIVACY_HELD")
    need("rows" not in receipt and "mapping" not in receipt and
         "private_answer_key" not in receipt,
         "CLAVIS_PRIVATE_CONTENT_HELD")
    return {"schema": "phistream.clavis.qualification-review.v0.3",
            "status": "RESEARCH_SUMMARY_NOT_SOURCE_BOUND",
            "receipt_sha256": digest(receipt)}


def correlate(repo: str, sha: str, gmed: dict, r14: dict,
              clavis: dict | None = None) -> dict:
    need(type(repo) is str and REPOSITORY.fullmatch(repo) is not None,
         "TARGET_REPOSITORY_INVALID")
    need(type(sha) is str and SHA40.fullmatch(sha) is not None,
         "EXPECTED_SOURCE_SHA_INVALID")
    observations = {
        "gmed": gmed_observation(gmed, sha),
        "agentora_r14": r14_observation(r14, repo, sha),
    }
    if clavis is not None:
        observations["phistream_clavis"] = clavis_observation(clavis)
    return {
        "schema": SCHEMA,
        "state": "CORRELATED_REVIEW_ONLY",
        "target_repository": repo,
        "source_sha": sha,
        "evidence": observations,
        "source_authentication_independent": False,
        "formal_proof_checked": False,
        "model_routing_activated": False,
        "code_write_authorized": False,
        "worker_dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "next_action": "Recheck original GitHub evidence, live SHA and independent human QA; separately run a trusted proof checker for formal claims.",
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--gmed", required=True, type=Path)
    p.add_argument("--r14", required=True, type=Path)
    p.add_argument("--clavis", type=Path,
                   help="optional public qualification summary; never private pack/key")
    args = p.parse_args(argv)
    try:
        report = correlate(args.repo, args.sha, load_public_summary(args.gmed),
                           load_public_summary(args.r14),
                           load_public_summary(args.clavis) if args.clavis else None)
    except (EvidenceHeld, OSError, OverflowError) as exc:
        p.exit(2, "PHI EVIDENCE WIRE HELD: " + str(exc) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
