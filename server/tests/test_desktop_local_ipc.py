"""Cross-platform R5 local IPC tests. Never connect to a real desktop."""
import json
import os
from pathlib import Path
import socket
import stat
import sys
from threading import Thread

import pytest

from app.services.desktop_bridge import (
    AgentDesktopCLI, DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit,
)
from app.services.desktop_broker import LocalDesktopBroker
from app.services.desktop_local_ipc import (
    ReadOnlyLocalIpc, _decode, _encode, _validate_address, doctor, request_ipc,
)

APP = "Calculator"
KEY = bytes(range(32))


def make_broker():
    calls = []

    def runner(argv):
        calls.append(argv)
        if argv[0] == "snapshot":
            return {
                "command": "snapshot", "ok": True, "version": "2.5",
                "data": {
                    "app": APP, "complete": True, "snapshot_id": "sabc123",
                    "tree": {
                        "role": "window", "children": [
                            {"ref_id": "@sabc123:e7", "role": "button", "name": "7",
                             "available_actions": ["Click"]},
                        ],
                    },
                },
            }
        raise AssertionError("Unexpected click or mutating command")

    bridge = DesktopBridge(
        DesktopPolicy(frozenset({APP}), enable_click=False),
        cli=AgentDesktopCLI(runner=runner), audit=LocalAudit(),
    )
    return LocalDesktopBroker(bridge, APP), calls


def ask_once(server, key_hex, operation):
    t = Thread(target=server.serve_one, daemon=True)
    t.start()
    try:
        return request_ipc(server.address, key_hex, operation)
    finally:
        t.join(timeout=5)
        assert not t.is_alive(), "IPC server hung after request"


def failure(code, callback):
    with pytest.raises(DesktopBridgeError) as exc:
        callback()
    assert exc.value.code == code


def test_authenticated_ping_never_observes(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setenv("HOME", str(tmp_path))
    broker, calls = make_broker()
    with ReadOnlyLocalIpc(broker, KEY) as server:
        reply = ask_once(server, KEY.hex(), "ping")
        assert reply["click_enabled"] is False
        assert calls == []


def test_observe_returns_refs_without_labels_by_default(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setenv("HOME", str(tmp_path))
    broker, calls = make_broker()
    with ReadOnlyLocalIpc(broker, KEY) as server:
        result = ask_once(server, KEY.hex(), "observe")
        assert result["count"] == 1
        assert result["items"][0]["name"] == ""
        assert result["labels_exposed"] is False
        assert [call[0] for call in calls] == ["snapshot"]


def test_mutating_operations_rejected_before_io():
    failure("ipc_request_not_supported",
            lambda: request_ipc("invalid", KEY.hex(), "click"))
    failure("ipc_request_not_supported",
            lambda: _decode(_encode({"v": 1, "op": "click"})))


def test_extra_request_keys_rejected():
    failure("ipc_request_not_supported",
            lambda: _decode(_encode({"v": 1, "op": "observe", "ref": "@s1:e1"})))


def test_requires_read_only_policy(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setenv("HOME", str(tmp_path))
    bridge = DesktopBridge(DesktopPolicy(frozenset({APP}), enable_click=True))
    broker = LocalDesktopBroker(bridge, APP)
    failure("read_only_bridge_required", lambda: ReadOnlyLocalIpc(broker, KEY))


def test_refuses_malformed_secret_and_address():
    failure("invalid_session_secret", lambda: request_ipc("invalid", "test", "ping"))
    failure("invalid_ipc_address", lambda: _validate_address("localhost:9999"))
    failure("invalid_ipc_address", lambda: _validate_address("http://127.0.0.1"))
    failure("ipc_request_not_supported", lambda: request_ipc("bad", KEY.hex(), "click"))


def test_wrong_session_key_denied_without_observation(monkeypatch, tmp_path):
    if os.name != "nt":
        monkeypatch.setenv("HOME", str(tmp_path))
    broker, calls = make_broker()
    with ReadOnlyLocalIpc(broker, KEY) as server:
        wrong = bytes(reversed(KEY)).hex()
        thread = Thread(target=server.serve_one, daemon=True)
        thread.start()
        try:
            failure("ipc_unavailable_or_rejected",
                    lambda: request_ipc(server.address, wrong, "observe"))
        finally:
            thread.join(timeout=5)
            assert not thread.is_alive()
        assert calls == []


def test_oversized_or_corrupt_payload_rejected():
    failure("ipc_frame_too_large", lambda: _decode(b"x" * 4097))
    failure("ipc_invalid_json", lambda: _decode(b"not-json"))


def test_private_socket_permissions_unix(monkeypatch, tmp_path):
    if os.name == "nt":
        pytest.skip("Windows named pipe has no filesystem mode")
    monkeypatch.setenv("HOME", str(tmp_path))
    broker, _ = make_broker()
    with ReadOnlyLocalIpc(broker, KEY) as server:
        path = Path(server.address)
        assert path.is_socket()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not path.exists()


def test_doctor_reports_windows_acl_as_unverified():
    report = doctor()
    assert report["read_only"] is True
    assert report["autonomous_action_path"] is False
    assert report["windows_pipe_acl_verified"] is False
    assert report["os_sandbox"] == "not_implemented"
