"""Φ Desktop Bridge R4: offline, read-only evidence field trial.

This module never clicks, calls the broker, uses a network endpoint, or invokes
Agentora's action API. A result reflects only what accessibility exposed; it
does NOT prove that a larger user task succeeded.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import json
import os
import platform
import secrets
import shutil
import sys
import time
from typing import Callable

from app.services.desktop_bridge import (
    DesktopBridge, DesktopBridgeError, DesktopPolicy, Observation,
)

TRANSITIONS = frozenset({"appeared", "disappeared"})
MAX_OBSERVATION_AGE = 300


@dataclass(frozen=True)
class EvidenceRule:
    """Exact role/name pairing; accessibility strings are untrusted inputs."""

    role: str
    name: str
    transition: str

    def __post_init__(self) -> None:
        for field, value, limit in (("role", self.role, 80), ("name", self.name, 120)):
            if (not isinstance(value, str) or not value or len(value) > limit
                    or value != value.strip()
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise DesktopBridgeError("invalid_" + field)
        if self.transition not in TRANSITIONS:
            raise DesktopBridgeError("invalid_transition")


@dataclass(frozen=True)
class EvidenceResult:
    status: str
    reason: str
    before_matches: int | None
    after_matches: int | None

    def receipt(self) -> dict[str, object]:
        """Privacy-minimal: no app, node names, refs, tokens or screen content."""
        return {
            "schema": 1,
            "receipt_id": secrets.token_hex(12),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": "local_accessibility_observation",
            "evidence_status": self.status,
            "reason_code": self.reason,
            "pre_match_count": self.before_matches,
            "post_match_count": self.after_matches,
            "task_verified": False,
            "desktop_action_executed_by_this_tool": False,
        }


def _count(observation: Observation, rule: EvidenceRule) -> int:
    return sum(
        1 for target in observation.targets.values()
        if target.role == rule.role and target.name == rule.name
    )


def assess(
    before: Observation,
    after: Observation,
    rule: EvidenceRule,
    *,
    now: float | None = None,
) -> EvidenceResult:
    """Require two distinct, fresh, same-app observations and an exact predicate.

    Even a supporting observation is not a confirmed user-level task result.
    """
    now = time.monotonic() if now is None else now
    if before.app != after.app:
        return EvidenceResult("inconclusive", "app_changed", None, None)
    if (before.snapshot_id == after.snapshot_id
            or after.captured_at <= before.captured_at):
        return EvidenceResult("inconclusive", "not_independent_snapshots", None, None)
    if (before.captured_at > now or after.captured_at > now
            or now - before.captured_at > MAX_OBSERVATION_AGE
            or now - after.captured_at > MAX_OBSERVATION_AGE):
        return EvidenceResult("inconclusive", "snapshot_out_of_window", None, None)

    pre = _count(before, rule)
    post = _count(after, rule)
    if pre > 1 or post > 1:
        return EvidenceResult("inconclusive", "ambiguous_duplicate_matches", pre, post)
    expected_pre, expected_post = (0, 1) if rule.transition == "appeared" else (1, 0)
    if (pre, post) == (expected_pre, expected_post):
        return EvidenceResult("supporting_observation", "expected_change_observed", pre, post)
    return EvidenceResult("contradicting_observation", "expected_change_not_observed", pre, post)


def doctor() -> dict[str, object]:
    """Read-only local capability report; does not probe the desktop."""
    return {
        "schema": 1,
        "platform": platform.system(),
        "python_supported": sys.version_info >= (3, 12),
        "interactive_terminal": sys.stdin.isatty() and sys.stdout.isatty(),
        "upstream_cli_on_path": shutil.which("agent-desktop") is not None,
        "native_tk_module": importlib.util.find_spec("tkinter") is not None,
        "broker_transport": "authenticated_loopback_tcp",
        "os_level_ipc_isolation": "not_implemented",
        "windows_acl_hardening": "not_implemented",
        "local_trial_mode": "observation_only",
        "note": "No desktop control is performed by doctor.",
    }


def supervised_trial(
    app: str,
    rule: EvidenceRule,
    *,
    bridge: DesktopBridge | None = None,
    confirm: Callable[[str], str] = input,
) -> EvidenceResult:
    """Capture BEFORE, let human act elsewhere, capture AFTER. No action here."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise DesktopBridgeError("interactive_operator_required")
    bridge = bridge or DesktopBridge(DesktopPolicy(frozenset({app})))
    if bridge.policy.enable_click:
        raise DesktopBridgeError("read_only_bridge_required")
    bridge.policy.check_app(app)
    print("Read-only trial. The app controls and terminal remain local.")
    print("Do not choose a sensitive application or include personal data in a rule.")
    if confirm("Type START to capture the initial observation: ").strip() != "START":
        raise DesktopBridgeError("operator_declined")
    before = bridge.observe(app)
    print("Initial observation captured. Make ONE harmless manual change in the app.")
    print("This tool will not perform any click, type or other desktop action.")
    if confirm("Type CAPTURE to take a fresh independent observation: ").strip() != "CAPTURE":
        raise DesktopBridgeError("operator_declined")
    after = bridge.observe(app)
    return assess(before, after, rule)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phi Desktop R4 read-only evidence field trial")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Local capability report, no desktop access")
    trial = sub.add_parser("trial", help="Supervised two-snapshot observation")
    trial.add_argument("--app", required=True)
    trial.add_argument("--role", required=True)
    trial.add_argument("--name", required=True)
    trial.add_argument("--expect", choices=sorted(TRANSITIONS), required=True)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(json.dumps(doctor(), indent=2, sort_keys=True))
        return 0
    try:
        rule = EvidenceRule(args.role, args.name, args.expect)
        result = supervised_trial(args.app, rule)
        print(json.dumps(result.receipt(), indent=2, sort_keys=True))
        return 0 if result.status == "supporting_observation" else 1
    except DesktopBridgeError as exc:
        print("Evidence trial stopped: " + exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
