"""Φ Desktop Bridge R6: Windows user-SID restricted, READ-ONLY named pipe.

Opt-in alternative to R5. Uses a Windows DACL created BEFORE binding, rejects
remote pipe clients and validates the impersonated client token SID. The R5
authkey handshake remains required. No action or click API exists.

Windows only: pywin32 312 is an optional runtime dependency. This is NOT a
sandbox and does not defend against malicious code already running as the
same Windows user or with administrative privileges.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import json
from multiprocessing import AuthenticationError
import os
import secrets
import sys
from typing import Any

from app.services.desktop_bridge import (
    DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit,
)
from app.services.desktop_broker import LocalDesktopBroker
from app.services.desktop_local_ipc import (
    MAX_FRAME, VERSION, _decode, _encode, _validate_address, request_ipc,
)

# These are Windows API bits, not arbitrary permission values.
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
FILE_ALL_ACCESS = 0x001F01FF


def _win():
    if os.name != "nt":
        raise DesktopBridgeError("windows_only")
    try:
        import _winapi
        import pywintypes
        import win32api
        import win32con
        import win32pipe
        import win32security
        from multiprocessing.connection import (
            PipeConnection, answer_challenge, deliver_challenge,
        )
        return (_winapi, pywintypes, win32api, win32con, win32pipe,
                win32security, PipeConnection, answer_challenge,
                deliver_challenge)
    except ImportError:
        raise DesktopBridgeError("pywin32_required") from None


def _user_sid(modules: tuple) -> str:
    _, _, win32api, win32con, _, security, *_ = modules
    with closing(security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )) as token:
        sid = security.GetTokenInformation(token, security.TokenUser)[0]
        return security.ConvertSidToStringSid(sid)


def _security_attributes(modules: tuple, sid_text: str):
    """Explicit, single-user DACL, never Windows' permissive pipe defaults."""
    _, pywintypes, _, _, _, security, *_ = modules
    sid = security.ConvertStringSidToSid(sid_text)
    acl = security.ACL()
    acl.AddAccessAllowedAce(FILE_ALL_ACCESS, sid)
    attrs = pywintypes.SECURITY_ATTRIBUTES()
    attrs.SetSecurityDescriptorDacl(1, acl, 0)
    return attrs


def _verify_bound_acl(handle: Any, modules: tuple, own_sid: str) -> None:
    """Inspect actual kernel object after bind, not just intended settings."""
    _, _, _, _, _, security, *_ = modules
    descriptor = security.GetSecurityInfo(
        handle, security.SE_KERNEL_OBJECT, security.DACL_SECURITY_INFORMATION,
    )
    acl = descriptor.GetSecurityDescriptorDacl()
    if acl is None or acl.GetAceCount() != 1:
        raise DesktopBridgeError("pipe_acl_invalid")
    ace = acl.GetAce(0)
    ace_type, ace_flags = ace[0]
    if (ace_type != 0 or ace_flags != 0
            or ace[1] != FILE_ALL_ACCESS
            or security.ConvertSidToStringSid(ace[2]) != own_sid):
        raise DesktopBridgeError("pipe_acl_invalid")


def _verify_client_sid(pipe_handle: int, modules: tuple, own_sid: str) -> None:
    """Revert impersonation unconditionally BEFORE any desktop observation."""
    _, _, win32api, win32con, _, security, *_ = modules
    impersonating = False
    try:
        security.ImpersonateNamedPipeClient(pipe_handle)
        impersonating = True
        with closing(security.OpenThreadToken(
            win32api.GetCurrentThread(), win32con.TOKEN_QUERY, True
        )) as token:
            sid = security.GetTokenInformation(token, security.TokenUser)[0]
            client_sid = security.ConvertSidToStringSid(sid)
    except Exception:
        raise DesktopBridgeError("pipe_client_identity_unavailable") from None
    finally:
        if impersonating:
            # Never handle a desktop request while impersonating the client.
            security.RevertToSelf()
    if client_sid != own_sid:
        raise DesktopBridgeError("pipe_client_sid_denied")


class WindowsRestrictedReadOnlyPipe:
    """Manual-start, single-client-at-a-time listener. Read-only by design."""

    def __init__(self, broker: LocalDesktopBroker, secret: bytes, address: str | None = None):
        if type(secret) is not bytes or len(secret) != 32:
            raise DesktopBridgeError("invalid_session_secret")
        if broker.bridge.policy.enable_click:
            raise DesktopBridgeError("read_only_bridge_required")
        modules = _win()
        self.modules = modules
        self.broker = broker
        self.secret = secret
        self.address = address or (r"\\.\pipe\phi-agentora-" + secrets.token_hex(12))
        if _validate_address(self.address) != "AF_PIPE":
            raise DesktopBridgeError("windows_named_pipe_required")
        self.owner_sid = _user_sid(modules)
        self._handle = None
        self._closed = False
        self._create_instance()

    def _create_instance(self) -> None:
        native, _, _, _, pipe, *_ = self.modules
        attrs = _security_attributes(self.modules, self.owner_sid)
        try:
            handle = pipe.CreateNamedPipe(
                self.address,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1, MAX_FRAME, MAX_FRAME, 0, attrs,
            )
        except Exception:
            raise DesktopBridgeError("pipe_bind_rejected") from None
        try:
            _verify_bound_acl(handle, self.modules, self.owner_sid)
        except Exception:
            handle.Close()
            raise
        self._handle = handle

    def serve_one(self) -> bool:
        """At most ONE authenticated, same-SID, observation-only request."""
        if self._closed:
            raise DesktopBridgeError("pipe_closed")
        if self._handle is None:
            self._create_instance()
        native, _, _, _, _, _, PipeConnection, answer, deliver = self.modules
        handle = self._handle
        self._handle = None
        connection = None
        try:
            # CPython's AF_PIPE transport expects OVERLAPPED handles.
            ov = native.ConnectNamedPipe(int(handle), overlapped=True)
            native.WaitForMultipleObjects([ov.event], False, native.INFINITE)
            ov.GetOverlappedResult(True)
            # PipeConnection owns the detached native handle from here onward.
            connection = PipeConnection(handle.Detach())
            with closing(connection):
                # Strictly require BOTH mutual authentication directions.
                deliver(connection, self.secret)
                answer(connection, self.secret)
                _verify_client_sid(connection.fileno(), self.modules, self.owner_sid)
                request = _decode(connection.recv_bytes(MAX_FRAME))
                if request["op"] == "ping":
                    data = self.broker.dispatch({"op": "ping"})
                elif request["op"] == "observe":
                    data = self.broker.dispatch({"op": "observe"})
                else:
                    raise DesktopBridgeError("ipc_request_not_supported")
                try:
                    connection.send_bytes(_encode({"v": VERSION, "ok": True, "result": data}))
                except (OSError, EOFError, DesktopBridgeError):
                    pass
            return True
        except (AuthenticationError, EOFError, OSError, DesktopBridgeError):
            return False
        finally:
            if connection is None:
                handle.Close()

    def close(self) -> None:
        self._closed = True
        if self._handle is not None:
            self._handle.Close()
            self._handle = None

    def __enter__(self) -> "WindowsRestrictedReadOnlyPipe":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def doctor() -> dict[str, object]:
    available = False
    sid_checked = False
    if os.name == "nt":
        try:
            _user_sid(_win())
            available = True
            sid_checked = True
        except DesktopBridgeError:
            pass
    return {
        "schema": 1,
        "platform": sys.platform,
        "windows_native_acl_backend_available": available,
        "process_token_sid_readable": sid_checked,
        "explicit_single_user_dacl": True,
        "reject_remote_pipe_clients": True,
        "validate_connected_sid": True,
        "mutating_commands_enabled": False,
        "os_sandbox": "not_implemented",
        "field_test_on_end_user_desktop": "not_performed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phi R6 Windows user-restricted read-only pipe")
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("doctor")
    start = sub.add_parser("start")
    start.add_argument("--app", required=True)
    start.add_argument("--expose-labels", action="store_true")
    request = sub.add_parser("request")
    request.add_argument("--address", required=True)
    request.add_argument("--op", choices=["ping", "observe"], required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "doctor":
            print(json.dumps(doctor(), indent=2))
            return 0
        if os.name != "nt":
            raise DesktopBridgeError("windows_only")
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise DesktopBridgeError("interactive_terminal_required")
        if args.mode == "start":
            broker = LocalDesktopBroker(
                DesktopBridge(
                    DesktopPolicy(frozenset({args.app}), enable_click=False),
                    audit=LocalAudit(),
                ),
                args.app,
                expose_labels=args.expose_labels,
            )
            secret = secrets.token_bytes(32)
            with WindowsRestrictedReadOnlyPipe(broker, secret) as server:
                print("R6 local pipe:", server.address, flush=True)
                print("PRIVATE one-session key:", secret.hex(), flush=True)
                print("Read-only: ping / observe only. Ctrl+C to stop.", flush=True)
                try:
                    while True:
                        server.serve_one()
                except KeyboardInterrupt:
                    return 0
        else:
            token = getpass.getpass("Local session key: ").strip()
            result = request_ipc(args.address, token, args.op)
            print(json.dumps(result, indent=2))
            return 0
    except DesktopBridgeError as exc:
        print("Restricted pipe unavailable: " + exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
