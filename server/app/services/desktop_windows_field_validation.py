"""Phi Desktop Bridge R7: supervised Windows read-only field validation.

Only requests ping and observe through the R6 user-restricted named pipe.
No click, typing, clipboard, shell, desktop-control, or HTTP path exists.
Reports are privacy-minimal; a passing probe never grants execution.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
import re
import secrets
import sys
from typing import Any, Callable

from app.services.desktop_bridge import DesktopBridgeError
from app.services.desktop_local_ipc import request_ipc
from app.services.desktop_windows_restricted_ipc import doctor as windows_doctor

SNAPSHOT = re.compile(r"s[A-Za-z0-9]{1,64}\Z")
MAX_VISIBLE_ITEMS = 16
MAX_COUNT = 100000


def _inspect_ping(reply: dict[str, Any]) -> None:
    if (not isinstance(reply, dict)
            or type(reply.get("protocol")) is not int
            or reply.get("protocol") != 1
            or reply.get("mode") != "local"
            or reply.get("transport") != "r6_windows_sid_pipe"
            or reply.get("click_enabled") is not False):
        raise DesktopBridgeError("field_broker_policy_mismatch")


def _inspect_observation(reply: dict[str, Any]) -> dict[str, Any]:
    """Verify shape, redaction, bounds; never copy app UI content to receipts."""
    if not isinstance(reply, dict):
        raise DesktopBridgeError("field_invalid_observation")
    if reply.get("labels_exposed") is not False:
        raise DesktopBridgeError("field_labels_or_schema_exposed")
    snapshot = reply.get("snapshot_id")
    count = reply.get("count")
    items = reply.get("items")
    truncated = reply.get("truncated")
    if (not isinstance(snapshot, str) or not SNAPSHOT.fullmatch(snapshot)
            or type(count) is not int or count < 0 or count > MAX_COUNT
            or not isinstance(items, list) or len(items) > MAX_VISIBLE_ITEMS
            or count < len(items)
            or type(truncated) is not bool
            or truncated != (count > len(items))):
        raise DesktopBridgeError("field_invalid_observation")
    for item in items:
        if (not isinstance(item, dict)
                or set(item) != {"ref", "role", "name"}
                or not isinstance(item["ref"], str)
                or not isinstance(item["role"], str)
                or item["name"] != ""
                or len(item["ref"]) > 80):
            raise DesktopBridgeError("field_labels_or_schema_exposed")
    return {
        "snapshot": snapshot,  # used only transiently to compare uniqueness
        "count": count,
        "truncated": truncated,
    }


def perform_probe(
    address: str,
    secret_hex: str,
    requester: Callable[[str, str, str], dict[str, Any]] = request_ipc,
    *,
    second_observation: bool = False,
    between: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """The only broker calls here are ping and observe.

    These calls do not interpret user actions, infer task completion or
    create any execution authorization token.
    """
    _inspect_ping(requester(address, secret_hex, "ping"))
    first = _inspect_observation(requester(address, secret_hex, "observe"))
    second_distinct: bool | None = None
    if second_observation:
        if between is None or between() is not True:
            raise DesktopBridgeError("field_operator_declined_second_observation")
        latter = _inspect_observation(requester(address, secret_hex, "observe"))
        second_distinct = latter["snapshot"] != first["snapshot"]
        if not second_distinct:
            raise DesktopBridgeError("field_duplicate_snapshot")
    return {
        "schema": 1,
        "receipt_id": secrets.token_hex(12),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "r6_user_restricted_read_only_pipe",
        "broker_reports_click_disabled": True,
        "r6_transport_marker_observed": True,
        "transport_identity_cryptographically_attested": False,
        "labels_redacted": True,
        "observation_metadata_valid": True,
        "observations_checked": 2 if second_observation else 1,
        "distinct_snapshot_ids": second_distinct,
        "first_observation_target_count": first["count"],
        "truncated": first["truncated"],
        "user_task_verified": False,
        "cross_user_dacl_negative_test": "NOT_PERFORMED",
        "real_windows_desktop_compatibility": "NOT_VERIFIED_BY_THIS_RECEIPT",
        "independent_security_review": "NOT_PERFORMED",
        "autonomous_execution_authorized": False,
        "mutating_action_requested": False,
    }


def readiness(report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explicitly separate automated checks from missing field assurances."""
    win = windows_doctor()
    return {
        "schema": 1,
        "platform": sys.platform,
        "windows_native_backend_available": win["windows_native_acl_backend_available"],
        "local_terminal_interactive": bool(
            sys.stdin.isatty() and sys.stdout.isatty()
        ),
        "reviewable_steps": [
            "R6 local named pipe has an explicit per-user DACL",
            "R6 validates bound ACL, client SID, and session authkey",
            "R7 checks read-only broker policy and redacted observations",
            "Independent multi-account denial test (manual)",
            "Real Windows application accessibility trial (manual)",
            "External security review before any mutation capability",
        ],
        "latest_probe_receipt_available": report is not None,
        "user_task_verified": False,
        "multi_account_access_restriction_field_verified": False,
        "ready_for_autonomous_desktop_actions": False,
    }


def _interactive() -> None:
    if os.name != "nt":
        raise DesktopBridgeError("windows_only")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise DesktopBridgeError("interactive_operator_required")


def run_supervised(
    address: str,
    *,
    ask: Callable[[str], str] = input,
    secret_prompt: Callable[[str], str] = getpass.getpass,
    requester: Callable[[str, str, str], dict[str, Any]] = request_ipc,
    two_observations: bool = False,
) -> dict[str, Any]:
    """Real local terminal consent required BEFORE accessing desktop metadata."""
    _interactive()
    if ask(
        "Observation-only Windows validation. Type READ ONLY to proceed: "
    ).strip() != "READ ONLY":
        raise DesktopBridgeError("field_operator_declined")
    key = secret_prompt("Private R6 session key (never saved): ").strip()

    def confirm_second() -> bool:
        print(
            "Optional: manually make ONE harmless change in the allowed app. "
            "No action is performed by this tool."
        )
        return ask("Type SECOND to capture another observation: ").strip() == "SECOND"

    return perform_probe(
        address, key, requester, second_observation=two_observations,
        between=confirm_second if two_observations else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phi R7 local read-only Windows validation; no clicks"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Offline readiness information, no desktop access")
    probe = sub.add_parser("probe", help="Explicit local observation through R6")
    probe.add_argument("--address", required=True, help="R6 local pipe address")
    probe.add_argument("--two-observations", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            print(json.dumps(readiness(), indent=2, sort_keys=True))
        else:
            report = run_supervised(
                args.address, two_observations=args.two_observations
            )
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except DesktopBridgeError as exc:
        print("Supervised R7 validation stopped: " + exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
