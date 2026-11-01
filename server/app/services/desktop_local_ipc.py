"""Phi Desktop Bridge R5: read-only local IPC transport prototype.

Uses authenticated stdlib AF_UNIX sockets or Windows AF_PIPE named pipes.
Never routes clicks, credentials, shell commands, or arbitrary tools.
This does NOT claim verified Windows pipe ACLs or same-user malware isolation.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import json
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Listener
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import struct
import sys
from typing import Any

from app.services.desktop_bridge import (
    DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit,
)
from app.services.desktop_broker import LocalDesktopBroker

VERSION = 1
MAX_FRAME = 4096
TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
NAME_PATTERN = re.compile(r"phi-agentora-[0-9a-f]{24}\.sock\Z")
PIPE_PATTERN = re.compile(r"\\\\\.\\pipe\\phi-agentora-[0-9a-f]{24}\Z")


def _directory() -> Path:
    """A private directory is essential on POSIX even before socket chmod."""
    directory = Path.home() / ".agentora" / "desktop-ipc"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink() or not directory.is_dir():
        raise DesktopBridgeError("insecure_ipc_directory")
    if os.name != "nt":
        if (directory.stat().st_mode & 0o077) or directory.stat().st_uid != os.getuid():
            raise DesktopBridgeError("insecure_ipc_directory")
    return directory


def _new_address() -> str:
    token = secrets.token_hex(12)
    if os.name == "nt":
        return r"\\.\pipe\phi-agentora-" + token
    address = str(_directory() / ("phi-agentora-" + token + ".sock"))
    if len(os.fsencode(address)) >= 100:
        raise DesktopBridgeError("ipc_path_too_long")
    return address


def _validate_address(address: str) -> str:
    if not isinstance(address, str):
        raise DesktopBridgeError("invalid_ipc_address")
    if os.name == "nt":
        if not PIPE_PATTERN.fullmatch(address):
            raise DesktopBridgeError("invalid_ipc_address")
        return "AF_PIPE"
    directory = _directory()
    path = Path(address)
    if (not path.is_absolute() or path.parent != directory
            or not NAME_PATTERN.fullmatch(path.name)
            or path.is_symlink()):
        raise DesktopBridgeError("invalid_ipc_address")
    return "AF_UNIX"


def _decode(packet: bytes) -> dict[str, Any]:
    if len(packet) > MAX_FRAME:
        raise DesktopBridgeError("ipc_frame_too_large")
    try:
        value = json.loads(packet.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DesktopBridgeError("ipc_invalid_json") from None
    if (not isinstance(value, dict)
            or set(value) != {"v", "op"}
            or type(value["v"]) is not int or value["v"] != VERSION
            or value["op"] not in ("ping", "observe")):
        raise DesktopBridgeError("ipc_request_not_supported")
    return value


def _encode(data: dict[str, Any]) -> bytes:
    raw = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    if len(raw) > MAX_FRAME:
        raise DesktopBridgeError("ipc_frame_too_large")
    return raw


def _check_unix_peer(conn: Any) -> None:
    """Fail closed when the current OS cannot verify peer UID."""
    if os.name == "nt":
        return  # Windows pipe ACL identity has NOT yet been independently verified.
    with closing(socket.socket(fileno=os.dup(conn.fileno()))) as peer:
        if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
            raw = peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            pid, uid, gid = struct.unpack("3i", raw)
            if pid <= 0 or uid != os.getuid():
                raise DesktopBridgeError("ipc_peer_not_current_user")
        elif hasattr(peer, "getpeereid"):
            uid, gid = peer.getpeereid()
            if uid != os.getuid():
                raise DesktopBridgeError("ipc_peer_not_current_user")
        else:
            raise DesktopBridgeError("ipc_peer_identity_unsupported")


class ReadOnlyLocalIpc:
    """An explicit one-app, read-only broker; no click dispatch exists."""

    def __init__(
        self,
        broker: LocalDesktopBroker,
        secret: bytes,
        address: str | None = None,
    ):
        if type(secret) is not bytes or len(secret) != 32:
            raise DesktopBridgeError("invalid_session_secret")
        if broker.bridge.policy.enable_click:
            raise DesktopBridgeError("read_only_bridge_required")
        self.broker = broker
        self.address = address or _new_address()
        family = _validate_address(self.address)
        if family == "AF_UNIX" and Path(self.address).exists():
            raise DesktopBridgeError("ipc_socket_already_exists")
        self.family = family
        self.listener = Listener(address=self.address, family=family, authkey=secret)
        if family == "AF_UNIX":
            os.chmod(self.address, 0o600)

    def serve_one(self) -> bool:
        """Accept one authenticated connection and at most one read-only request."""
        try:
            connection = self.listener.accept()
        except (OSError, AuthenticationError, EOFError):
            return False
        with closing(connection):
            try:
                _check_unix_peer(connection)
                frame = connection.recv_bytes(MAX_FRAME)
                request = _decode(frame)
                if request["op"] == "ping":
                    data = self.broker.dispatch({"op": "ping"})
                else:
                    data = self.broker.dispatch({"op": "observe"})
                response = {"v": VERSION, "ok": True, "result": data}
            except (DesktopBridgeError, ValueError, EOFError):
                response = {"v": VERSION, "ok": False, "error": "request_denied"}
            except (OSError, RuntimeError):
                response = {"v": VERSION, "ok": False, "error": "backend_unavailable"}
            try:
                connection.send_bytes(_encode(response))
            except (DesktopBridgeError, OSError, EOFError):
                pass
        return True

    def close(self) -> None:
        self.listener.close()
        if self.family == "AF_UNIX":
            try:
                Path(self.address).unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "ReadOnlyLocalIpc":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def request_ipc(address: str, secret_hex: str, operation: str) -> dict[str, Any]:
    if operation not in ("ping", "observe"):
        raise DesktopBridgeError("ipc_request_not_supported")
    if (not isinstance(secret_hex, str)
            or not TOKEN_PATTERN.fullmatch(secret_hex)):
        raise DesktopBridgeError("invalid_session_secret")
    family = _validate_address(address)
    try:
        with closing(Client(address=address, family=family, authkey=bytes.fromhex(secret_hex))) as conn:
            conn.send_bytes(_encode({"v": VERSION, "op": operation}))
            response = json.loads(conn.recv_bytes(MAX_FRAME).decode("utf-8"))
    except (AuthenticationError, OSError, EOFError, UnicodeError, ValueError):
        raise DesktopBridgeError("ipc_unavailable_or_rejected") from None
    if (not isinstance(response, dict)
            or response.get("v") != VERSION
            or type(response.get("ok")) is not bool):
        raise DesktopBridgeError("ipc_invalid_response")
    if not response["ok"]:
        raise DesktopBridgeError("ipc_request_denied")
    result = response.get("result")
    if not isinstance(result, dict):
        raise DesktopBridgeError("ipc_invalid_response")
    return result


def doctor() -> dict[str, Any]:
    return {
        "platform": sys.platform,
        "transport": "AF_PIPE" if os.name == "nt" else "AF_UNIX",
        "read_only": True,
        "requires_session_authkey": True,
        "unix_peer_uid_checked": sys.platform.startswith("linux"),
        "windows_pipe_acl_verified": False,
        "os_sandbox": "not_implemented",
        "autonomous_action_path": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phi read-only native local IPC R5")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("doctor")
    start = sub.add_parser("start")
    start.add_argument("--app", required=True)
    start.add_argument("--expose-labels", action="store_true")
    ask = sub.add_parser("request")
    ask.add_argument("--address", required=True)
    ask.add_argument("--op", required=True, choices=["ping", "observe"])
    args = parser.parse_args(argv)
    try:
        if args.mode == "doctor":
            print(json.dumps(doctor(), indent=2))
            return 0
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise DesktopBridgeError("interactive_terminal_required")
        if args.mode == "start":
            policy = DesktopPolicy(frozenset({args.app}), enable_click=False)
            broker = LocalDesktopBroker(
                DesktopBridge(policy, audit=LocalAudit()), args.app,
                expose_labels=args.expose_labels,
            )
            secret = secrets.token_bytes(32)
            with ReadOnlyLocalIpc(broker, secret) as server:
                print("Local IPC address:", server.address, flush=True)
                print("Local session secret (keep PRIVATE):", secret.hex(), flush=True)
                print("Observation-only. Ctrl+C to stop.", flush=True)
                try:
                    while True:
                        server.serve_one()
                except KeyboardInterrupt:
                    return 0
        token = getpass.getpass("Local session secret: ").strip()
        result = request_ipc(args.address, token, args.op)
        print(json.dumps(result, indent=2))
        return 0
    except DesktopBridgeError as exc:
        print("Local IPC stopped: " + exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
