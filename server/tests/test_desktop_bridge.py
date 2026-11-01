"""R0 bridge contract tests use fake envelopes, never a real desktop."""
import io
import json
import sys

import pytest

from app.services.desktop_bridge import (
    AgentDesktopCLI, DesktopBridge, DesktopBridgeError, DesktopPolicy, LocalAudit,
)

APP = "Calculator"
REF = "@sabc123:e7"
SECRET = "private-password-abc"


def snapshot(*, complete=True, app=APP, name="7", actions=None):
    return {
        "command": "snapshot", "ok": True, "version": "2.5",
        "data": {
            "app": app, "complete": complete, "snapshot_id": "sabc123",
            "tree": {"role": "window", "children": [
                {"role": "button", "ref_id": REF,
                 "available_actions": ["Click"] if actions is None else actions,
                 "name": name},
            ]},
        },
    }


def result(delivery="delivered_unverified"):
    return {"command": "click", "ok": True, "version": "2.5",
            "data": {"disposition": {"delivery": delivery, "retry": "unsafe"}}}


def make_bridge(*, allow=False, name="7", post=None, click=None, complete=True):
    commands = []
    responses = [snapshot(name=name, complete=complete),
                 click if click is not None else result(),
                 post if post is not None else snapshot()]
    def runner(argv):
        commands.append(argv)
        return responses.pop(0)
    audit = LocalAudit()
    bridge = DesktopBridge(DesktopPolicy(frozenset({APP}), enable_click=allow),
                           AgentDesktopCLI(runner=runner), audit)
    return bridge, commands, audit


def assert_error(code, function):
    with pytest.raises(DesktopBridgeError) as exc:
        function()
    assert exc.value.code == code


def test_default_read_only_never_clicks():
    bridge, commands, audit = make_bridge()
    assert REF in bridge.observe(APP).targets
    assert_error("click_disabled", lambda: bridge.click(REF))
    assert [c[0] for c in commands] == ["snapshot"]
    assert all(SECRET not in json.dumps(e) for e in audit.events)


def test_unknown_application_fails_before_backend():
    bridge, commands, _ = make_bridge()
    assert_error("app_not_allowlisted", lambda: bridge.observe("Other app"))
    assert commands == []


def test_incomplete_snapshot_rejected():
    bridge, _, _ = make_bridge(complete=False)
    assert_error("incomplete_or_wrong_app", lambda: bridge.observe(APP))


def test_unobserved_or_nonclickable_ref_rejected():
    bridge, commands, _ = make_bridge(allow=True)
    bridge.observe(APP)
    assert_error("not_observed_clickable_ref", lambda: bridge.click("@sabc123:e8"))
    assert [c[0] for c in commands] == ["snapshot"]


def test_protected_label_denied_even_with_write_enabled():
    bridge, commands, audit = make_bridge(allow=True, name="Delete all files")
    bridge.observe(APP)
    assert_error("protected_target", lambda: bridge.click(REF))
    assert len(commands) == 1
    assert "Delete all files" not in json.dumps(audit.events)


def test_agent_or_ci_cannot_approve_without_interactive_terminal():
    bridge, commands, _ = make_bridge(allow=True)
    bridge.observe(APP)
    assert_error("interactive_operator_required", lambda: bridge.click(REF))
    assert len(commands) == 1


def test_operator_decline_blocks_mutation(monkeypatch):
    bridge, commands, _ = make_bridge(allow=True)
    bridge.observe(APP)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "NO")
    assert_error("operator_declined", lambda: bridge.click(REF))
    assert len(commands) == 1


def test_confirmed_click_runs_once_and_reports_unverified(monkeypatch):
    bridge, commands, audit = make_bridge(allow=True)
    bridge.observe(APP)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("app.services.desktop_bridge.secrets.token_hex", lambda _: "00000000")
    monkeypatch.setattr("builtins.input", lambda _: "APPROVE 00000000")
    response = bridge.click(REF)
    assert response.delivery == "delivered_unverified"
    assert response.post_observed is True
    assert response.verified is False
    assert [c[0] for c in commands] == ["snapshot", "click", "snapshot"]
    assert audit.events[-1]["status"] == "completed"


def test_backend_uncertainty_is_not_retried(monkeypatch):
    click_error = {
        "command": "click", "ok": False, "version": "2.5",
        "error": {"code": "TIMEOUT", "message": SECRET,
                  "disposition": {"delivery": "unknown", "retry": "unknown"}},
    }
    bridge, commands, audit = make_bridge(allow=True, click=click_error)
    bridge.observe(APP)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("app.services.desktop_bridge.secrets.token_hex", lambda _: "00000000")
    monkeypatch.setattr("builtins.input", lambda _: "APPROVE 00000000")
    assert_error("backend_timeout", lambda: bridge.click(REF))
    assert [c[0] for c in commands] == ["snapshot", "click"]
    assert SECRET not in json.dumps(audit.events)


def test_backend_never_executes_arbitrary_commands():
    cli = AgentDesktopCLI(runner=lambda _: None)
    assert_error("command_not_supported", lambda: cli.invoke("clipboard-get"))


def test_local_audit_file_contains_only_metadata(tmp_path):
    path = tmp_path / "bridge.jsonl"
    ledger = LocalAudit(path)
    ledger.record("observe", "ok")
    assert json.loads(path.read_text())["operation"] == "observe"
    assert SECRET not in path.read_text()
