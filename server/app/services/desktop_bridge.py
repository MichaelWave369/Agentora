"""Φ Desktop Bridge R0: local-only, governed adapter for vercel-labs/agent-desktop.

No HTTP route, no background daemon, no implicit permission grants. The OS process
running this module is the trust boundary; do not expose it to remote agents.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REF_RE = re.compile(r"@(?P<snapshot>s[a-zA-Z0-9]+):e[0-9]+")
SNAP_RE = re.compile(r"s[a-zA-Z0-9]+")
# Defense in depth only. Accessibility labels are not a security boundary.
PROTECTED_LABEL_RE = re.compile(
    r"\b(delete|remove|erase|wipe|format|reset|purchase|buy|pay|transfer|"
    r"send|submit|publish|install|uninstall|merge|approve|authorize|grant|"
    r"sign|log\s*out|sign\s*out|password|credential|security|permission)\b",
    re.IGNORECASE,
)


class DesktopBridgeError(RuntimeError):
    """An intentionally content-free failure suitable for local audit records."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DesktopPolicy:
    allowed_apps: frozenset[str]
    enable_click: bool = False
    max_age_seconds: int = 30

    def check_app(self, app: str) -> None:
        if not app or app not in self.allowed_apps:
            raise DesktopBridgeError("app_not_allowlisted")


@dataclass(frozen=True)
class Target:
    ref: str
    role: str
    name: str
    actions: frozenset[str]


@dataclass
class Observation:
    app: str
    snapshot_id: str
    targets: dict[str, Target]
    captured_at: float


@dataclass(frozen=True)
class ClickResult:
    delivery: str
    post_observed: bool
    verified: bool = False  # Observing afterwards is not proof of intent.


class LocalAudit:
    """Content-free JSONL ledger, stored only on the local machine."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.events: list[dict[str, str]] = []

    def record(self, operation: str, status: str, code: str = "") -> None:
        event = {
            "time": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "status": status,
            "code": code,
        }
        self.events.append(event)
        if self.path is None:
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")


class AgentDesktopCLI:
    """Strict argv-only subprocess adapter. No shell, env secrets, or stderr logs."""

    def __init__(
        self,
        binary: str = "agent-desktop",
        runner: Callable[[list[str]], dict] | None = None,
    ):
        self.binary = binary
        self.runner = runner

    def invoke(self, *args: str) -> dict:
        if args[0] not in {"snapshot", "click"}:
            raise DesktopBridgeError("command_not_supported")
        if self.runner is not None:
            envelope = self.runner(list(args))
        else:
            executable = shutil.which(self.binary)
            if not executable:
                raise DesktopBridgeError("agent_desktop_not_installed")
            try:
                process = subprocess.run(
                    [executable, *args], shell=False, text=True,
                    capture_output=True, timeout=20, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise DesktopBridgeError("backend_unavailable") from None
            if len(process.stdout) > 1_048_576:
                raise DesktopBridgeError("backend_response_too_large")
            try:
                envelope = json.loads(process.stdout)
            except (TypeError, ValueError):
                raise DesktopBridgeError("backend_invalid_json") from None
        if not isinstance(envelope, dict) or envelope.get("command") != args[0]:
            raise DesktopBridgeError("backend_invalid_envelope")
        if envelope.get("ok") is not True:
            # Error messages/suggestions can contain user data. Never forward them.
            error = envelope.get("error") or {}
            code = error.get("code") if isinstance(error, dict) else ""
            if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9_]{1,60}", code):
                code = "BACKEND_REJECTED"
            raise DesktopBridgeError("backend_" + code.lower())
        if not isinstance(envelope.get("data"), dict):
            raise DesktopBridgeError("backend_missing_data")
        return envelope["data"]


def _targets_from_tree(tree: dict, snapshot_id: str) -> dict[str, Target]:
    if not isinstance(tree, dict):
        raise DesktopBridgeError("snapshot_invalid_tree")
    targets: dict[str, Target] = {}
    stack = [tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            raise DesktopBridgeError("snapshot_invalid_tree")
        ref = node.get("ref_id")
        if isinstance(ref, str):
            match = REF_RE.fullmatch(ref)
            if not match or match.group("snapshot") != snapshot_id:
                raise DesktopBridgeError("snapshot_invalid_ref")
            raw_actions = node.get("available_actions", [])
            if not isinstance(raw_actions, list):
                raise DesktopBridgeError("snapshot_invalid_actions")
            targets[ref] = Target(
                ref=ref,
                role=str(node.get("role", ""))[:80],
                name=str(node.get("name", ""))[:200],
                actions=frozenset(a for a in raw_actions if isinstance(a, str)),
            )
        children = node.get("children", [])
        if not isinstance(children, list):
            raise DesktopBridgeError("snapshot_invalid_tree")
        stack.extend(children)
        if len(stack) + len(targets) > 20_000:
            raise DesktopBridgeError("snapshot_too_many_nodes")
    return targets


def _safe_console_text(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c)[0] != "C")[:120]


class DesktopBridge:
    def __init__(
        self,
        policy: DesktopPolicy,
        cli: AgentDesktopCLI | None = None,
        audit: LocalAudit | None = None,
    ):
        if not policy.allowed_apps:
            raise DesktopBridgeError("app_allowlist_required")
        self.policy = policy
        self.cli = cli or AgentDesktopCLI()
        self.audit = audit or LocalAudit()
        self._observation: Observation | None = None

    def observe(self, app: str) -> Observation:
        self.policy.check_app(app)
        data = self.cli.invoke("snapshot", "--app", app, "-i")
        if data.get("app") != app or data.get("complete") is not True:
            self.audit.record("observe", "denied", "incomplete_or_wrong_app")
            raise DesktopBridgeError("incomplete_or_wrong_app")
        sid = data.get("snapshot_id")
        if not isinstance(sid, str) or not SNAP_RE.fullmatch(sid):
            raise DesktopBridgeError("snapshot_invalid_id")
        targets = _targets_from_tree(data.get("tree"), sid)
        observation = Observation(app, sid, targets, time.monotonic())
        self._observation = observation
        self.audit.record("observe", "ok")
        return observation

    def click(self, ref: str) -> ClickResult:
        """One approved click, never a batch; post-snapshot is not proof of success."""
        observation = self._observation
        if not self.policy.enable_click:
            self.audit.record("click", "denied", "click_disabled")
            raise DesktopBridgeError("click_disabled")
        if observation is None or time.monotonic() - observation.captured_at > self.policy.max_age_seconds:
            self.audit.record("click", "denied", "snapshot_expired")
            raise DesktopBridgeError("snapshot_expired")
        self.policy.check_app(observation.app)
        target = observation.targets.get(ref)
        if not target or "Click" not in target.actions:
            self.audit.record("click", "denied", "not_observed_clickable_ref")
            raise DesktopBridgeError("not_observed_clickable_ref")
        if PROTECTED_LABEL_RE.search(target.name):
            self.audit.record("click", "denied", "protected_target")
            raise DesktopBridgeError("protected_target")
        # Never allow an agent, CI, or web request to silently authorize a click.
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            self.audit.record("click", "denied", "interactive_operator_required")
            raise DesktopBridgeError("interactive_operator_required")
        challenge = "APPROVE " + secrets.token_hex(4)
        print(
            "Local desktop action requested:\n"
            f"Application: {_safe_console_text(observation.app)}\n"
            f"Target: {_safe_console_text(target.role)} | {_safe_console_text(target.name)}\n"
            f"Ref: {target.ref}\n"
            "This may have irreversible effects. No action is guaranteed safe.",
            flush=True,
        )
        if input(f"Type {challenge} to execute exactly one click: ").strip() != challenge:
            self.audit.record("click", "denied", "operator_declined")
            raise DesktopBridgeError("operator_declined")

        # Consume observation before sending. No implicit replay on any outcome.
        self._observation = None
        try:
            data = self.cli.invoke("click", ref)
        except DesktopBridgeError as exc:
            self.audit.record("click", "uncertain", exc.code)
            raise
        disposition = data.get("disposition")
        delivery = disposition.get("delivery") if isinstance(disposition, dict) else None
        if delivery not in {
            "not_delivered", "delivered_unverified", "delivered_verified",
            "delivery_uncertain", "unknown",
        }:
            delivery = "unknown"
        post_observed = False
        try:
            self.observe(observation.app)
            post_observed = True
        except DesktopBridgeError:
            pass
        self.audit.record("click", "completed", str(delivery))
        return ClickResult(delivery=delivery, post_observed=post_observed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only governed desktop observation")
    parser.add_argument("--app", required=True, help="Exact app name, e.g. Calculator")
    parser.add_argument("--enable-click", action="store_true", help="Enable one TTY-approved click")
    parser.add_argument("--audit-file", type=Path, default=None, help="Local private JSONL ledger path")
    args = parser.parse_args()
    bridge = DesktopBridge(
        DesktopPolicy(frozenset({args.app}), enable_click=args.enable_click),
        audit=LocalAudit(args.audit_file),
    )
    try:
        obs = bridge.observe(args.app)
        refs = [t for t in obs.targets.values() if "Click" in t.actions]
        print(f"Observed {len(refs)} clickable refs locally. No screenshot or tree uploaded.")
        for i, target in enumerate(refs[:40], 1):
            print(f"{i:2}. {target.ref} {_safe_console_text(target.role)}: {_safe_console_text(target.name)}")
        if args.enable_click:
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise DesktopBridgeError("interactive_operator_required")
            selected = input("Choose a displayed number (empty to cancel): ").strip()
            if not selected:
                return 0
            if not selected.isdecimal() or not 1 <= int(selected) <= min(len(refs), 40):
                raise DesktopBridgeError("invalid_selection")
            result = bridge.click(refs[int(selected) - 1].ref)
            print(f"Delivery: {result.delivery}; observed after: {result.post_observed}; verified: {result.verified}")
        return 0
    except DesktopBridgeError as exc:
        print(f"Desktop bridge stopped: {exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
