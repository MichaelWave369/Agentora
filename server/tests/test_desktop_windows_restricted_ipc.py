"""R6 Windows real named-pipe/ACL test (mock desktop). No user files or clicks."""
import json
import os
import sys
from threading import Thread

import pytest

from app.services.desktop_bridge import (
    AgentDesktopCLI, DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit,
)
from app.services.desktop_broker import LocalDesktopBroker
from app.services.desktop_local_ipc import request_ipc
from app.services import desktop_windows_restricted_ipc as secure

KEY = bytes(range(32))
APP = "Calculator"
windows_only = pytest.mark.skipif(os.name != "nt", reason="requires Windows named pipes")


def broker(click=False):
    calls = []

    def runner(argv):
        calls.append(tuple(argv))
        if argv[0] != "snapshot":
            raise AssertionError("No desktop mutation allowed")
        return {
            "command": "snapshot", "ok": True, "version": "2.5",
            "data": {
                "app": APP, "complete": True, "snapshot_id": "sabc123",
                "tree": {"role": "window", "children": [
                    {"ref_id": "@sabc123:e7", "role": "button", "name": "7",
                     "available_actions": ["Click"]},
                ]},
            },
        }

    bridge = DesktopBridge(
        DesktopPolicy(frozenset({APP}), enable_click=click),
        cli=AgentDesktopCLI(runner=runner), audit=LocalAudit(),
    )
    return LocalDesktopBroker(bridge, APP), calls


def assert_code(code, fn):
    with pytest.raises(DesktopBridgeError) as error:
        fn()
    assert error.value.code == code


def client_once(server, token, operation="ping"):
    thread = Thread(target=server.serve_one, daemon=True)
    thread.start()
    try:
        return request_ipc(server.address, token, operation)
    finally:
        thread.join(timeout=8)
        assert not thread.is_alive(), "server did not terminate request"


def test_doctor_reports_no_os_sandbox_or_autonomy():
    report = secure.doctor()
    assert report["os_sandbox"] == "not_implemented"
    assert report["mutating_commands_enabled"] is False
    assert report["field_test_on_end_user_desktop"] == "not_performed"


def test_not_supported_on_unix():
    if os.name != "nt":
        b, _ = broker()
        assert_code("windows_only", lambda: secure.WindowsRestrictedReadOnlyPipe(b, KEY))


@windows_only
def test_windows_pipe_binds_with_one_user_dacl():
    b, _ = broker()
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY) as server:
        assert server.owner_sid.startswith("S-1-")
        secure._verify_bound_acl(server._handle, server.modules, server.owner_sid)
        assert server.address.startswith("\\\\.\\pipe\\phi-agentora-")
        assert server.family if hasattr(server, "family") else True


@windows_only
def test_authenticated_same_sid_ping():
    b, calls = broker()
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY) as server:
        result = client_once(server, KEY.hex())
    assert result["click_enabled"] is False
    assert calls == []


@windows_only
def test_authenticated_observation_redacts_labels_and_cannot_click():
    b, calls = broker()
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY) as server:
        result = client_once(server, KEY.hex(), "observe")
    assert result["items"][0]["name"] == ""
    assert len(calls) == 1 and calls[0][0] == "snapshot"
    assert_code("ipc_request_not_supported",
                lambda: request_ipc(server.address, KEY.hex(), "click"))


@windows_only
def test_wrong_key_rejected_without_touching_desktop():
    b, calls = broker()
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY) as server:
        thread = Thread(target=server.serve_one, daemon=True)
        thread.start()
        try:
            assert_code(
                "ipc_unavailable_or_rejected",
                lambda: request_ipc(server.address, bytes(reversed(KEY)).hex(), "observe"),
            )
        finally:
            thread.join(timeout=8)
            assert not thread.is_alive()
    assert calls == []


@windows_only
def test_client_sid_check_fails_closed(monkeypatch):
    b, calls = broker()
    def forbidden(*args):
        raise DesktopBridgeError("pipe_client_sid_denied")
    monkeypatch.setattr(secure, "_verify_client_sid", forbidden)
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY) as server:
        thread = Thread(target=server.serve_one, daemon=True)
        thread.start()
        try:
            assert_code(
                "ipc_unavailable_or_rejected",
                lambda: request_ipc(server.address, KEY.hex(), "observe"),
            )
        finally:
            thread.join(timeout=8)
            assert not thread.is_alive()
    assert calls == []


@windows_only
def test_windows_pipe_creation_rejects_remote_clients(monkeypatch):
    modules = secure._win()
    pipe = modules[4]
    real_create = pipe.CreateNamedPipe
    observed = []

    def capture(*args):
        observed.append((args[1], args[2]))
        return real_create(*args)

    monkeypatch.setattr(pipe, "CreateNamedPipe", capture)
    b, _ = broker()
    with secure.WindowsRestrictedReadOnlyPipe(b, KEY):
        assert observed
        access, mode = observed[0]
        assert access & secure.FILE_FLAG_FIRST_PIPE_INSTANCE
        assert access & secure.FILE_FLAG_OVERLAPPED
        assert mode & secure.PIPE_REJECT_REMOTE_CLIENTS


@windows_only
def test_no_secure_pipe_when_click_policy_enabled():
    b, _ = broker(click=True)
    assert_code(
        "read_only_bridge_required",
        lambda: secure.WindowsRestrictedReadOnlyPipe(b, KEY),
    )


@windows_only
def test_session_secret_rejected_before_bind():
    b, _ = broker()
    assert_code(
        "invalid_session_secret",
        lambda: secure.WindowsRestrictedReadOnlyPipe(b, b"bad"),
    )
