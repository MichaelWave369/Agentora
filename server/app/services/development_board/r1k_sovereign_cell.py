"""R1-K: strict, pure-stdlib read-only Sovereign Cell manifest inspection.

Inspired by high-level nine-organ / 3-6-9 cell architecture: a DECLARATION,
not proof of operational resilience, security, auth, or automatic permission.
Never loads user code, evaluates source, grants rights, or writes a repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "examples/development-board/sovereign-cell.json"
SCHEMA = "phi369.sovereign-cell.manifest.v0.1"
ORGANS = (
    "face", "mind", "memory", "hands", "body", "shield",
    "pulse", "continuity", "seed",
)
TIERS = {
    "being": ["face", "mind", "memory"],
    "function": ["hands", "body", "shield"],
    "sovereignty": ["pulse", "continuity", "seed"],
}
PRINCIPLES = (
    "one_module", "one_manifest", "one_runtime", "one_recovery_path",
    "local_first", "observable_by_default", "secure_by_default",
    "easy_to_inspect", "easy_to_restore",
)
ASSESSMENTS = frozenset(("PARTIAL", "NOT_DEMONSTRATED", "EVIDENCED_CLAIM_ONLY"))
ALLOWED_FILES = (
    "server/app/",
    "server/tests/",
    "docs/",
    ".github/workflows/",
    "examples/development-board/",
)
PATH = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,180}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
MAX_MANIFEST_BYTES = 12 * 1024
MAX_EVIDENCE_BYTES = 256 * 1024
MAX_EVIDENCE_FILES = 30
REVIEW_SCHEMA = "agentora.devboard.r1k.sovereign-cell-review.v1"


class CellRefusal(ValueError):
    """Fixed error code, never raw untrusted document/source text."""


def _require(test: bool, code: str) -> None:
    if not test:
        raise CellRefusal(code)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _exact(value: Any, keys: tuple[str, ...] | set[str]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _string(value: Any, maximum: int) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= maximum
            and value == value.strip() and all(ord(c) >= 32 for c in value))


def _path_ok(value: Any) -> bool:
    return (
        isinstance(value, str) and PATH.fullmatch(value) is not None
        and not value.startswith("/") and "\\" not in value
        and all(segment not in ("", ".", "..") for segment in value.split("/"))
        and any(value.startswith(prefix) for prefix in ALLOWED_FILES)
    )


def parse_manifest(raw: bytes) -> dict[str, Any]:
    _require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_MANIFEST_BYTES,
             "MANIFEST_SIZE_REFUSED")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CellRefusal("MANIFEST_JSON_REFUSED") from exc
    _require(_exact(data, {
        "schema", "cell", "declared_architecture", "tiers",
        "organs", "principles", "authority",
    }) and data["schema"] == SCHEMA, "MANIFEST_SCHEMA_REFUSED")

    cell = data["cell"]
    _require(_exact(cell, ("id", "purpose", "scope", "maturity_claim"))
             and cell["id"] == "agentora_development_board"
             and _string(cell["purpose"], 300)
             and cell["scope"] == "SINGLE_DEVELOPMENT_BOARD_CAPABILITY_NOT_WHOLE_REPOSITORY"
             and cell["maturity_claim"] == "DESIGN_PILOT_NOT_SOVEREIGN_CERTIFIED",
             "CELL_IDENTITY_REFUSED")

    deployment = data["declared_architecture"]
    _require(_exact(deployment, {
        "deployment", "runtime", "single_process", "local_first", "automatic_recovery"
    }) and deployment == {
        "deployment": "MIXED_LOCAL_AND_GITHUB_ACTIONS_MANUAL",
        "runtime": "MULTI_PROCESS_WITH_SEPARATE_VERIFIERS",
        "single_process": "NOT_DEMONSTRATED",
        "local_first": "PARTIALLY_DEMONSTRATED",
        "automatic_recovery": "NOT_DEMONSTRATED",
    }, "RUNTIME_CLAIM_REFUSED")

    _require(data["tiers"] == TIERS, "NINE_ORGAN_TIER_MAPPING_REFUSED")
    organs = data["organs"]
    _require(_exact(organs, set(ORGANS)), "NINE_ORGANS_REQUIRED")
    paths: set[str] = set()
    for organ in ORGANS:
        entry = organs[organ]
        _require(_exact(entry, ("responsibility", "evidence_paths"))
                 and _string(entry["responsibility"], 220),
                 "ORGAN_METADATA_REFUSED")
        refs = entry["evidence_paths"]
        _require(isinstance(refs, list) and 1 <= len(refs) <= 3
                 and all(_path_ok(ref) for ref in refs)
                 and len(refs) == len(set(refs)), "ORGAN_EVIDENCE_PATH_REFUSED")
        paths.update(refs)
    _require(len(paths) <= MAX_EVIDENCE_FILES, "EVIDENCE_COUNT_REFUSED")

    principles = data["principles"]
    _require(_exact(principles, set(PRINCIPLES)), "NINE_PRINCIPLES_REQUIRED")
    for name in PRINCIPLES:
        entry = principles[name]
        _require(_exact(entry, ("assessment", "note"))
                 and entry["assessment"] in ASSESSMENTS
                 and _string(entry["note"], 240),
                 "PRINCIPLE_ASSESSMENT_REFUSED")
    # Assert the known gaps as explicit facts. A declaration must not quietly
    # upgrade a design-only pilot to an operational, self-healing cell.
    for gap in ("one_runtime", "one_recovery_path", "easy_to_restore"):
        _require(principles[gap]["assessment"] == "NOT_DEMONSTRATED",
                 "UNVERIFIED_SOVEREIGNTY_CLAIM_REFUSED")
    _require(principles["local_first"]["assessment"] == "PARTIAL",
             "LOCAL_FIRST_OVERCLAIM_REFUSED")

    authority = data["authority"]
    _require(_exact(authority, {
        "repository_write", "automatic_merge", "deploy", "issue_creation",
        "agent_spawn", "release_authorized", "sovereignty_certified",
    }) and all(value is False for value in authority.values()),
             "AUTHORITY_ESCALATION_REFUSED")
    return data


def _evidence_file(root: Path, relative: str) -> bytes:
    _require(_path_ok(relative), "EVIDENCE_PATH_REFUSED")
    # lstat on every component refuses symlinks, including parent directories.
    cursor = root
    for component in relative.split("/"):
        cursor = cursor / component
        _require(not cursor.is_symlink(), "EVIDENCE_SYMLINK_REFUSED")
    _require(cursor.is_file(), "EVIDENCE_FILE_MISSING")
    size = cursor.stat().st_size
    _require(0 < size <= MAX_EVIDENCE_BYTES, "EVIDENCE_SIZE_REFUSED")
    with cursor.open("rb") as stream:
        raw = stream.read(MAX_EVIDENCE_BYTES + 1)
    _require(len(raw) == size, "EVIDENCE_CHANGED_DURING_READ")
    return raw


def inspect(raw: bytes, root: Path, claimed_commit: str) -> dict[str, Any]:
    _require(isinstance(root, Path) and root.is_dir()
             and not root.is_symlink(), "ROOT_REFUSED")
    _require(isinstance(claimed_commit, str) and SHA40.fullmatch(claimed_commit),
             "COMMIT_PIN_REFUSED")
    data = parse_manifest(raw)
    organs = data["organs"]
    evidence = sorted({
        evidence_path
        for organ in ORGANS
        for evidence_path in organs[organ]["evidence_paths"]
    })
    evidence_hashes = [{
        "path": item,
        "sha256": hashlib.sha256(_evidence_file(root, item)).hexdigest(),
    } for item in evidence]
    gaps = [name for name in PRINCIPLES
            if data["principles"][name]["assessment"] == "NOT_DEMONSTRATED"]
    # Inspect references and their exact bytes: no source execution or assertion
    # that path existence proves the listed feature actually works.
    return {
        "schema": REVIEW_SCHEMA,
        "status": "NINE_ORGANS_DECLARED_REVIEW_ONLY",
        "cell_id": data["cell"]["id"],
        "source_commit_sha_claim": claimed_commit,
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_manifest_sha256": hashlib.sha256(canonical_bytes(data)).hexdigest(),
        "organs_declared": len(ORGANS),
        "tiers_declared": {name: "DECLARED_NOT_OPERATIONALLY_CERTIFIED" for name in TIERS},
        "principles_checked": len(PRINCIPLES),
        "evidence_files_present": len(evidence_hashes),
        "evidence_file_sha256": evidence_hashes,
        "unmet_or_unproven_principles": gaps,
        "readiness": "NOT_SOVEREIGN_QUALIFIED",
        "proof_limitation": "PATH_AND_HASH_CONSISTENCY_NOT_FEATURE_OR_RECOVERY_ATTESTATION",
        "model_executed": False,
        "repository_writes": False,
        "deployment_executed": False,
        "release_authorized": False,
        "eligible_for_merge": False,
        "automatic_merge": False,
        "human_review_required": True,
    }


def verify_receipt(raw_manifest: bytes, root: Path, sha: str, receipt: Any) -> bool:
    # Deliberately recompute from fresh repo bytes, not trust stored judgments.
    return isinstance(receipt, dict) and receipt == inspect(raw_manifest, root, sha)


def main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Read-only Sovereign Cell Contract pilot")
    parser.add_argument("--output-dir", type=Path, required=True)
    opts = parser.parse_args(args)
    try:
        _require(os.getenv("GITHUB_ACTIONS") == "true"
                 and os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch",
                 "MANUAL_GITHUB_WORKFLOW_REQUIRED")
        sha = os.getenv("GITHUB_SHA", "")
        out = opts.output_dir
        _require(out.is_dir() and not out.is_symlink() and not list(out.iterdir()),
                 "SCRATCH_OUTPUT_REFUSED")
        raw_manifest = _evidence_file(ROOT, "examples/development-board/sovereign-cell.json")
        result = inspect(raw_manifest, ROOT, sha)
        # A fresh second pass verifies what will be exported. Neither pass runs
        # imported repository code or grants runtime powers.
        _require(verify_receipt(raw_manifest, ROOT, sha, result),
                 "INDEPENDENT_READBACK_REFUSED")
        target = out / "sovereign-cell-review.json"
        with target.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write("\n")
        print(json.dumps({
            "status": result["status"],
            "organs_declared": result["organs_declared"],
            "evidence_files_present": result["evidence_files_present"],
            "readiness": result["readiness"],
            "repository_writes": False, "eligible_for_merge": False,
        }, sort_keys=True))
        return 0
    except (CellRefusal, OSError, ValueError, TypeError):
        print(json.dumps({
            "status": "HELD", "reason": "SOVEREIGN_CELL_CONTRACT_REFUSED",
            "repository_writes": False, "eligible_for_merge": False,
        }))
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
