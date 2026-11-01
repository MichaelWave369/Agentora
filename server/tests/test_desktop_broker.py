"""R1 broker tests use localhost and fake accessibility envelopes; no actual desktop."""
import json
import socket
import threading

import pytest

from app.services.desktop_bridge import AgentDesktopCLI, DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit
from app.services.desktop_broker import (
    MAX_LINE, LocalDesktopBroker, _canonical, _line, create_server, request_local,
)

APP = "Calculator"
REF = "@sabc123:e7"
TOKEN = bytes(range(32))


def observation(name="7"):
    return {"version": "2.5", "command": "snapshot", "ok": True,
            "data": {"app": APP, "complete": True, "snapshot_id": "sabc123",
                     "tree": {"role": "window", "children": [
                         {"role": "button", "ref_id": REF, "name": name, "available_actions": ["Click"]},
                     ]}}}


def fake_broker(*, enable_click=False, expose_labels=False, name="7"):
    calls = []
    def runner(argv):
        calls.append(argv)
        if argv[0] == "snapshot":
            return observation(name=name)
        return {"version": "2.5", "command": "click", "ok": True,
                "data": {"disposition": {"delivery": "delivered_unverified", "retry": "unsafe"}}}
    audit = LocalAudit()
    bridge = DesktopBridge(
        DesktopPolicy(frozenset({APP}), enable_click=enable_click),
        cli=AgentDesktopCLI(runner=runner),
        audit=audit,
    )
    return LocalDesktopBroker(bridge, APP, expose_labels=expose_labels), calls, audit


@pytest.fixture
def live():
    broker, calls, audit = fake_broker()
    with create_server(broker, TOKEN) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server.server_address[1], broker, calls, audit
        finally:
            server.shutdown()
            thread.join(timeout=3)


def assert_error(code, callback):
    with pytest.raises(DesktopBridgeError) as exc:
        callback()
    assert exc.value.code == code


def test_auth_client_can_ping_without_desktop(live):
    port, _, calls, _ = live
    response = request_local(port, TOKEN.hex(), {"op": "ping"})
    assert response["protocol"] == 1
    assert response["click_enabled"] is False
    assert calls == []


def test_auth_rejects_wrong_token_without_observation(live):
    port, _, calls, audit = live
    assert_error("authentication_failed", lambda: request_local(port, bytes(reversed(TOKEN)).hex(), {"op": "observe"}))
    assert calls == []
    assert audit.events[-1]["code"] == "authentication_failed"


def test_observe_redacts_accessibility_names_by_default(live):
    port, _, calls, audit = live
    result = request_local(port, TOKEN.hex(), {"op": "observe"})
    assert result["items"] == [{"ref": REF, "role": "button", "name": ""}]
    assert result["count"] == 1
    assert result["labels_exposed"] is False
    assert calls[0][0] == "snapshot"
    assert all("Calculator" not in json.dumps(event) for event in audit.events)


def test_name_sharing_requires_explicit_broker_setting():
    broker, _, _ = fake_broker(expose_labels=True, name="Sample label")
    result = broker.dispatch({"op": "observe"})
    assert result["labels_exposed"] is True
    assert result["items"][0]["name"] == "Sample label"


def test_read_only_click_refused_over_authenticated_ipc(live):
    port, _, calls, _ = live
    request_local(port, TOKEN.hex(), {"op": "observe"})
    assert_error("click_disabled", lambda: request_local(port, TOKEN.hex(), {"op": "click", "ref": REF}))
    assert [row[0] for row in calls] == ["snapshot"]


def test_unsupported_ops_and_unknown_fields_rejected(live):
    port, _, calls, _ = live
    assert_error("request_not_supported", lambda: request_local(port, TOKEN.hex(), {"op": "shell"}))
    assert_error("request_not_supported", lambda: request_local(port, TOKEN.hex(), {"op": "observe", "app": "Other"}))
    assert calls == []


def test_click_requires_broker_terminal_even_if_authenticated():
    broker, calls, _ = fake_broker(enable_click=True)
    broker.dispatch({"op": "observe"})
    assert_error("interactive_operator_required", lambda: broker.dispatch({"op": "click", "ref": REF}))
    assert [row[0] for row in calls] == ["snapshot"]


def test_protected_click_refused_before_approval():
    broker, calls, _ = fake_broker(enable_click=True, name="Delete files")
    broker.dispatch({"op": "observe"})
    assert_error("protected_target", lambda: broker.dispatch({"op": "click", "ref": REF}))
    assert [row[0] for row in calls] == ["snapshot"]


def test_human_approves_click_at_broker_not_in_request(monkeypatch):
    import sys
    broker, calls, _ = fake_broker(enable_click=True)
    broker.dispatch({"op": "observe"})
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("app.services.desktop_bridge.secrets.token_hex", lambda _: "abcdef01")
    monkeypatch.setattr("builtins.input", lambda prompt: "APPROVE abcdef01")
    result = broker.dispatch({"op": "click", "ref": REF})
    assert result == {"delivery": "delivered_unverified", "post_observed": True, "verified": False}
    assert [row[0] for row in calls] == ["snapshot", "click", "snapshot"]


def test_challenge_different_each_connection(live):
    port, _, _, _ = live
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c1:
        first = json.loads(c1.makefile("rb").readline())
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c2:
        second = json.loads(c2.makefile("rb").readline())
    assert first["challenge"] != second["challenge"]


def test_broker_never_binds_public_interface(live):
    port, _, _, _ = live
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        assert connection.getpeername()[0] == "127.0.0.1"


def test_oversized_request_rejected_without_backend_action(live):
    port, _, calls, _ = live
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        stream = connection.makefile("rwb")
        stream.readline()
        stream.write(b"x" * (MAX_LINE + 10) + b"\n")
        stream.flush()
        response = json.loads(stream.readline())
        assert response["ok"] is False
    assert calls == []


def test_client_validation_rejects_non_hex_token_before_connection():
    assert_error("invalid_token", lambda: request_local(1, "secret", {"op": "ping"}))
    assert_error("invalid_port", lambda: request_local(0, TOKEN.hex(), {"op": "ping"}))


def test_signature_never_includes_secret_on_wire():
    assert TOKEN.hex().encode() not in _line({"op": "ping"})
