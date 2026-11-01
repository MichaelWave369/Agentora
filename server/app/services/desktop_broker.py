"""Φ Desktop Bridge R1: explicitly launched, authenticated localhost broker.

This is a process boundary, not an OS security boundary. The broker never
creates a remote listener. Every mutation is independently approved on the
broker's own interactive terminal by the existing R0 guard.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import re
import secrets
import socket
import socketserver
import sys
from pathlib import Path
from typing import Any

from app.services.desktop_bridge import (
    DesktopBridge,
    DesktopBridgeError,
    DesktopPolicy,
    LocalAudit,
    _safe_console_text,
)

PROTOCOL_VERSION = 1
MAX_LINE = 8192
MAX_TARGETS = 16
CHALLENGE_RE = re.compile(r"[0-9a-f]{64}\Z")
TOKEN_RE = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _line(obj: dict[str, Any]) -> bytes:
    result = _canonical(obj) + b"\n"
    if len(result) > MAX_LINE:
        raise DesktopBridgeError("response_too_large")
    return result


def _read_line(stream: Any) -> dict[str, Any]:
    raw = stream.readline(MAX_LINE + 1)
    if not raw or len(raw) > MAX_LINE or not raw.endswith(b"\n"):
        raise DesktopBridgeError("invalid_frame")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise DesktopBridgeError("invalid_json") from None
    if not isinstance(value, dict):
        raise DesktopBridgeError("invalid_frame")
    return value


def _signature(secret: bytes, challenge: str, request: dict[str, Any]) -> str:
    if not CHALLENGE_RE.fullmatch(challenge):
        raise DesktopBridgeError("invalid_challenge")
    return hmac.new(secret, challenge.encode("ascii") + b":" + _canonical(request), hashlib.sha256).hexdigest()


class LocalDesktopBroker:
    """Keep the upstream DesktopBridge and its approval prompt in this process."""

    def __init__(self, bridge: DesktopBridge, app: str, *, expose_labels: bool = False):
        bridge.policy.check_app(app)
        self.bridge = bridge
        self.app = app
        self.expose_labels = expose_labels

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        op = request.get("op")
        if op == "ping" and set(request) == {"op"}:
            return {"protocol": PROTOCOL_VERSION, "mode": "local", "click_enabled": self.bridge.policy.enable_click}
        if op == "observe" and set(request) == {"op"}:
            observation = self.bridge.observe(self.app)
            targets = [
                {
                    "ref": target.ref,
                    "role": _safe_console_text(target.role),
                    "name": _safe_console_text(target.name) if self.expose_labels else "",
                }
                for target in observation.targets.values()
                if "Click" in target.actions and len(target.ref) <= 80
            ]
            return {
                "snapshot_id": observation.snapshot_id,
                "count": len(targets),
                "items": targets[:MAX_TARGETS],
                "truncated": len(targets) > MAX_TARGETS,
                "labels_exposed": self.expose_labels,
            }
        if op == "click" and set(request) == {"op", "ref"}:
            ref = request.get("ref")
            if not isinstance(ref, str):
                raise DesktopBridgeError("invalid_ref")
            result = self.bridge.click(ref)
            return {
                "delivery": result.delivery,
                "post_observed": result.post_observed,
                "verified": result.verified,
            }
        raise DesktopBridgeError("request_not_supported")


class _LoopbackServer(socketserver.TCPServer):
    allow_reuse_address = False
    request_queue_size = 4

    def __init__(self, broker: LocalDesktopBroker, secret: bytes, port: int = 0):
        if len(secret) != 32:
            raise ValueError("secret_must_have_256_bits")
        self.broker = broker
        self.secret = secret
        # This bound address is intentionally constant and not caller supplied.
        super().__init__(("127.0.0.1", port), _Handler, bind_and_activate=True)


class _Handler(socketserver.StreamRequestHandler):
    def _reply(self, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        response = {"v": PROTOCOL_VERSION, "ok": error is None}
        if error is None:
            response["result"] = result or {}
        else:
            response["error"] = error
        try:
            self.wfile.write(_line(response))
            self.wfile.flush()
        except (OSError, DesktopBridgeError):
            pass

    def handle(self) -> None:
        server: _LoopbackServer = self.server
        self.request.settimeout(8)
        challenge = secrets.token_hex(32)
        try:
            self.wfile.write(_line({"v": PROTOCOL_VERSION, "challenge": challenge}))
            self.wfile.flush()
            packet = _read_line(self.rfile)
            request = packet.get("request")
            mac = packet.get("mac")
            if (
                packet.get("v") != PROTOCOL_VERSION
                or set(packet) != {"v", "request", "mac"}
                or not isinstance(request, dict)
                or not isinstance(mac, str)
                or not re.fullmatch(r"[0-9a-f]{64}", mac)
                or not hmac.compare_digest(mac, _signature(server.secret, challenge, request))
            ):
                server.broker.bridge.audit.record("ipc", "denied", "authentication_failed")
                self._reply(error="authentication_failed")
                return
            try:
                response = server.broker.dispatch(request)
                self._reply(result=response)
            except DesktopBridgeError as exc:
                self._reply(error=exc.code)
            except Exception:
                # Backend exceptions must never disclose private app contents.
                server.broker.bridge.audit.record("ipc", "failed", "internal_error")
                self._reply(error="internal_error")
        except (OSError, DesktopBridgeError, ValueError):
            server.broker.bridge.audit.record("ipc", "denied", "malformed_request")
            self._reply(error="malformed_request")


def create_server(
    broker: LocalDesktopBroker,
    secret: bytes,
    port: int = 0,
) -> socketserver.TCPServer:
    """Caller owns server lifetime. A zero port lets the OS choose a free one."""
    return _LoopbackServer(broker, secret, port)


def request_local(port: int, token_hex: str, request: dict[str, Any]) -> dict[str, Any]:
    """Authenticated client helper. Never log or persist the token."""
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise DesktopBridgeError("invalid_port")
    if not isinstance(token_hex, str) or not TOKEN_RE.fullmatch(token_hex):
        raise DesktopBridgeError("invalid_token")
    if not isinstance(request, dict):
        raise DesktopBridgeError("invalid_request")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=30) as connection:
            connection.settimeout(30)
            with connection.makefile("rwb") as stream:
                greeting = _read_line(stream)
                challenge = greeting.get("challenge")
                if greeting.get("v") != PROTOCOL_VERSION or not isinstance(challenge, str):
                    raise DesktopBridgeError("invalid_challenge")
                signature = _signature(bytes.fromhex(token_hex), challenge, request)
                stream.write(_line({"v": PROTOCOL_VERSION, "request": request, "mac": signature}))
                stream.flush()
                response = _read_line(stream)
    except (OSError, TimeoutError):
        raise DesktopBridgeError("broker_unavailable") from None
    if response.get("v") != PROTOCOL_VERSION or not isinstance(response.get("ok"), bool):
        raise DesktopBridgeError("invalid_response")
    if response["ok"] is False:
        error = response.get("error")
        if not isinstance(error, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", error):
            error = "request_denied"
        raise DesktopBridgeError(error)
    result = response.get("result")
    if not isinstance(result, dict):
        raise DesktopBridgeError("invalid_response")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Φ Desktop Bridge: local broker R1")
    sub = parser.add_subparsers(dest="mode", required=True)
    server_command = sub.add_parser("start", help="Start a manually controlled local broker")
    server_command.add_argument("--app", required=True)
    server_command.add_argument("--port", type=int, default=0)
    server_command.add_argument("--enable-click", action="store_true")
    server_command.add_argument("--expose-labels", action="store_true")
    server_command.add_argument("--audit-file", type=Path)
    client_command = sub.add_parser("request", help="Send one authenticated request locally")
    client_command.add_argument("--port", required=True, type=int)
    client_command.add_argument("--op", choices=["ping", "observe", "click"], required=True)
    client_command.add_argument("--ref")
    args = parser.parse_args(argv)
    try:
        if args.mode == "start":
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise DesktopBridgeError("broker_requires_interactive_terminal")
            if not 0 <= args.port <= 65535:
                raise DesktopBridgeError("invalid_port")
            bridge = DesktopBridge(
                DesktopPolicy(frozenset({args.app}), enable_click=args.enable_click),
                audit=LocalAudit(args.audit_file),
            )
            broker = LocalDesktopBroker(bridge, args.app, expose_labels=args.expose_labels)
            secret = secrets.token_bytes(32)
            with create_server(broker, secret, args.port) as server:
                print(f"Local-only Φ broker on 127.0.0.1:{server.server_address[1]}", flush=True)
                print("Session token (enter in the other local terminal, never share):", flush=True)
                print(secret.hex(), flush=True)
                print("Read-only unless --enable-click. Ctrl+C to stop.", flush=True)
                try:
                    server.serve_forever(poll_interval=0.2)
                except KeyboardInterrupt:
                    pass
            return 0
        if args.op == "click" and not args.ref:
            raise DesktopBridgeError("ref_required")
        if args.op != "click" and args.ref:
            raise DesktopBridgeError("unexpected_ref")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise DesktopBridgeError("client_requires_interactive_terminal")
        token = getpass.getpass("Local session token: ").strip()
        request = {"op": args.op}
        if args.ref:
            request["ref"] = args.ref
        response = request_local(args.port, token, request)
        print(json.dumps(response, indent=2, ensure_ascii=True))
        return 0
    except DesktopBridgeError as exc:
        print(f"Desktop broker stopped: {exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
