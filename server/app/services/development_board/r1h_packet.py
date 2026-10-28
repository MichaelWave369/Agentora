"""R1-H: manual, GitHub-hosted, NO-WRITE coding task review envelope.

ONLY a fixed, committed TOY Python file. The proposed source is INERT text.
The envelope is deliberately INCOMPATIBLE with PhiBot's seven-field governed
write request. No model/network/read of a live repository/PR authorization.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
TARGET = "examples/development-board/r1h-demo-label.py"
BEFORE = (
    'def normalize_label(value):\n'
    '    """Collapse repeated whitespace in a display label."""\n'
    '    return " ".join(value.split())\n'
)
AFTER = (
    'def normalize_label(value):\n'
    '    """Collapse repeated whitespace in a display label."""\n'
    '    if not isinstance(value, str):\n'
    '        raise TypeError("label must be text")\n'
    '    return " ".join(value.split())\n'
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DOMAIN = b"agentora.r1h.readonly-coding-task.v1\n"
SCHEMA = "agentora.devboard.r1h.readonly-coding-task.v1"
MAX_PACKET = 4096
ACCEPTANCE = [
    "REVIEW_ONLY_TOY_FIXTURE",
    "ADD_EXACT_TYPE_GUARD_WITHOUT_OTHER_CHANGES",
    "EXISTING_LABEL_NORMALIZATION_PRESERVED_FOR_STRINGS",
    "NO_CODE_EXECUTION_OR_GITHUB_WRITES",
]


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def packet_for(commit_sha: str) -> dict:
    if not isinstance(commit_sha, str) or HEX40.fullmatch(commit_sha) is None:
        raise ValueError("EXACT_40_HEX_COMMIT_REQUIRED")
    path = ROOT / TARGET
    if path.is_symlink() or not path.is_file() or path.read_bytes() != BEFORE.encode("utf-8"):
        raise ValueError("TOY_FIXTURE_MISMATCH")
    data = {
        "schema": SCHEMA,
        "producer": "Agentora",
        "repository": "MichaelWave369/Agentora",
        "target_path": TARGET,
        "source_commit_sha_claim": commit_sha,
        "task_id": "R1H-TOY-LABEL-TYPE-GUARD",
        "task_kind": "INERT_SINGLE_FILE_SOURCE_PREVIEW_ONLY",
        "provenance": "GITHUB_ACTIONS_SELF_REPORTED_NOT_ATTESTED",
        "source_before": BEFORE,
        "source_after_preview": AFTER,
        "source_before_sha256": _sha(BEFORE.encode("utf-8")),
        "source_after_sha256": _sha(AFTER.encode("utf-8")),
        "acceptance_checks": ACCEPTANCE,
        "authority": {
            "repository_writes": False,
            "issue_creation": False,
            "pr_creation": False,
            "merge": False,
            "deploy": False,
            "approval_authenticated": False,
            "phibot_executed": False,
        },
        "disposition": "PHIBOT_INSPECT_ONLY_NOT_A_WRITE_REQUEST",
    }
    data["packet_sha256"] = _sha(DOMAIN + _canonical(data))
    return data


def validate_packet(packet: object, expected_commit: str | None = None) -> dict:
    try:
        if not isinstance(packet, dict) or set(packet) != set(packet_for(
                packet.get("source_commit_sha_claim", ""))):
            raise ValueError("PACKET_KEYS_INVALID")
        if expected_commit is not None and packet["source_commit_sha_claim"] != expected_commit:
            raise ValueError("PACKET_COMMIT_MISMATCH")
        original = packet_for(packet["source_commit_sha_claim"])
        if packet != original or _canonical(packet) != _canonical(original):
            raise ValueError("PACKET_EXACT_TOY_CONTRACT_MISMATCH")
        return {
            "schema": "agentora.devboard.r1h.packet-review.v1",
            "status": "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY",
            "packet_sha256": packet["packet_sha256"],
            "source_commit_sha_claim": packet["source_commit_sha_claim"],
            "phibot_executed": False,
            "write_authorized": False,
            "eligible_for_merge": False,
        }
    except (OSError, ValueError, TypeError, KeyError):
        return {
            "schema": "agentora.devboard.r1h.packet-review.v1",
            "status": "HELD",
            "reason": "PACKET_REFUSED",
            "phibot_executed": False,
            "write_authorized": False,
            "eligible_for_merge": False,
        }


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def prepare_cloud(output_dir: Path, commit_sha: str) -> dict:
    if (output_dir.is_symlink() or not output_dir.is_dir()
            or list(output_dir.iterdir())):
        raise ValueError("OUTPUT_DIRECTORY_INVALID")
    packet = packet_for(commit_sha)
    verdict = validate_packet(packet, expected_commit=commit_sha)
    if verdict["status"] != "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY":
        raise ValueError("PREPARE_REFUSED")
    serialized = _canonical(packet)
    if len(serialized) > MAX_PACKET:
        raise ValueError("PACKET_TOO_LARGE")
    # All writes are to a fresh, disposable GitHub Actions artifact directory.
    _write_new(output_dir / "phibot-review-packet.json", serialized + b"\n")
    _write_new(output_dir / "phibot-review-packet.base64url.txt",
               base64.urlsafe_b64encode(serialized).rstrip(b"=") + b"\n")
    _write_new(output_dir / "agentora-review-receipt.json",
               json.dumps(verdict, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    return verdict


def recheck_artifact(output_dir: Path, commit_sha: str) -> dict:
    try:
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError("INVALID_DIR")
        allowed = {
            "phibot-review-packet.json", "phibot-review-packet.base64url.txt",
            "agentora-review-receipt.json",
        }
        if {p.name for p in output_dir.iterdir()} != allowed:
            raise ValueError("UNEXPECTED_ARTIFACTS")
        paths = [output_dir / name for name in sorted(allowed)]
        if any(p.is_symlink() or not p.is_file() for p in paths):
            raise ValueError("SYMLINK_OR_MISSING")
        raw = (output_dir / "phibot-review-packet.json").read_bytes()
        if len(raw) > MAX_PACKET + 1 or not raw.endswith(b"\n"):
            raise ValueError("PACKET_FILE_SIZE")
        packet = json.loads(raw.decode("utf-8"))
        if raw != _canonical(packet) + b"\n":
            raise ValueError("PACKET_ENCODING_CHANGED")
        choice = (output_dir / "phibot-review-packet.base64url.txt").read_bytes()
        if choice != base64.urlsafe_b64encode(raw[:-1]).rstrip(b"=") + b"\n":
            raise ValueError("COPY_PAYLOAD_CHANGED")
        verdict = validate_packet(packet, expected_commit=commit_sha)
        receipt = json.loads((output_dir / "agentora-review-receipt.json").read_text("utf-8"))
        if verdict["status"] != "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY" or receipt != verdict:
            raise ValueError("EVIDENCE_INVALID")
        return verdict
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {
            "status": "HELD", "reason": "PACKET_RECHECK_REFUSED",
            "phibot_executed": False, "write_authorized": False,
            "eligible_for_merge": False,
        }


def main(args: list[str]) -> int:
    cli = argparse.ArgumentParser(description="R1-H disposable PhiBot-read-only coding task envelope")
    sub = cli.add_subparsers(dest="action", required=True)
    for action in ("prepare", "recheck"):
        command = sub.add_parser(action)
        command.add_argument("--output-dir", type=Path, required=True)
    opts = cli.parse_args(args)
    if os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("GITHUB_EVENT_NAME") != "workflow_dispatch":
        print(json.dumps({"status": "HELD", "reason": "MANUAL_CLOUD_DISPATCH_REQUIRED"}))
        return 2
    commit = os.getenv("GITHUB_SHA", "")
    try:
        result = (prepare_cloud(opts.output_dir, commit) if opts.action == "prepare"
                  else recheck_artifact(opts.output_dir, commit))
    except (OSError, ValueError, TypeError):
        result = {"status": "HELD", "reason": "PACKET_PREPARE_REFUSED"}
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
