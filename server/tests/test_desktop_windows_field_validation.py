"""R7 reviewable field-validation contract tests. No computer control."""
import json
import os
import re
import sys

import pytest

from app.services.desktop_bridge import DesktopBridgeError
from app.services import desktop_windows_field_validation as field


def ping(allowed=False):
    return {"protocol": 1, "mode": "local",
            "transport": "r6_windows_sid_pipe", "click_enabled": allowed}


def observation(snapshot="sabc123", count=1, expose=False):
    return {
        "snapshot_id": snapshot,
        "count": count,
        "items": [{"ref": f"@{snapshot}:e7", "role": "button",
                   "name": "7" if expose else ""}],
        "truncated": False,
        "labels_exposed": expose,
    }


def expect(code, fn):
    with pytest.raises(DesktopBridgeError) as exc:
        fn()
    assert exc.value.code == code


def make_requester(results):
    results = iter(results)
    calls = []

    def request(address, key, op):
        calls.append(op)
        assert address == "local-address"
        assert key == "TEST_ONLY_PRIVATE_SESSION"
        return next(results)

    return request, calls


def test_one_observation_receipt_never_authorizes_actions():
    call, calls = make_requester([ping(), observation()])
    report = field.perform_probe("local-address", "TEST_ONLY_PRIVATE_SESSION", call)
    assert calls == ["ping", "observe"]
    assert report["broker_reports_click_disabled"] is True
    assert report["labels_redacted"] is True
    assert report["user_task_verified"] is False
    assert report["autonomous_execution_authorized"] is False
    assert report["mutating_action_requested"] is False
    assert report["cross_user_dacl_negative_test"] == "NOT_PERFORMED"
    serialized = json.dumps(report)
    for secret in ("TEST_ONLY_PRIVATE_SESSION", "local-address", "@sabc123", "button"):
        assert secret not in serialized


def test_two_independent_observations_do_not_prove_task():
    call, calls = make_requester([ping(), observation(), observation("sdef456")])
    report = field.perform_probe(
        "local-address", "TEST_ONLY_PRIVATE_SESSION", call,
        second_observation=True, between=lambda: True,
    )
    assert calls == ["ping", "observe", "observe"]
    assert report["distinct_snapshot_ids"] is True
    assert report["user_task_verified"] is False


def test_second_capture_needs_explicit_operator_consent():
    call, calls = make_requester([ping(), observation()])
    expect(
        "field_operator_declined_second_observation",
        lambda: field.perform_probe(
            "local-address", "TEST_ONLY_PRIVATE_SESSION", call,
            second_observation=True, between=lambda: False,
        ),
    )
    assert calls == ["ping", "observe"]


def test_no_recycled_snapshots_as_independent_evidence():
    call, calls = make_requester([ping(), observation(), observation()])
    expect(
        "field_duplicate_snapshot",
        lambda: field.perform_probe(
            "local-address", "TEST_ONLY_PRIVATE_SESSION", call,
            second_observation=True, between=lambda: True,
        ),
    )
    assert calls == ["ping", "observe", "observe"]


def test_observation_prevented_if_click_enabled():
    call, calls = make_requester([ping(True)])
    expect(
        "field_broker_policy_mismatch",
        lambda: field.perform_probe("local-address", "TEST_ONLY_PRIVATE_SESSION", call),
    )
    assert calls == ["ping"]


@pytest.mark.parametrize("reply", [
    {},
    {"protocol": 1, "mode": "remote", "click_enabled": False},
    {"protocol": 1, "mode": "local", "click_enabled": 0},
    {"protocol": 2, "mode": "local", "click_enabled": False},
])
def test_broker_ping_fail_closed(reply):
    call, calls = make_requester([reply])
    expect(
        "field_broker_policy_mismatch",
        lambda: field.perform_probe("local-address", "TEST_ONLY_PRIVATE_SESSION", call),
    )
    assert calls == ["ping"]


@pytest.mark.parametrize("bad, expected_code", [
    (observation(expose=True), "field_labels_or_schema_exposed"),
    (observation("bad snapshot!"), "field_invalid_observation"),
    ({**observation(), "truncated": True}, "field_invalid_observation"),
    ({**observation(), "count": -1}, "field_invalid_observation"),
    ({**observation(), "count": True}, "field_invalid_observation"),
    ({**observation(), "count": 0}, "field_invalid_observation"),
    ({**observation(), "items": "not-list"}, "field_invalid_observation"),
    ({**observation(), "items": [{"ref": "@sabc:e1", "role": "button", "name": "secret"}]},
     "field_labels_or_schema_exposed"),
    ({**observation(), "items": [{"ref": "x" * 90, "role": "button", "name": ""}]},
     "field_labels_or_schema_exposed"),
])
def test_redaction_and_response_schema_are_enforced(bad, expected_code):
    call, calls = make_requester([ping(), bad])
    expect(
        expected_code,
        lambda: field.perform_probe("local-address", "TEST_ONLY_PRIVATE_SESSION", call),
    )
    assert calls == ["ping", "observe"]


def test_doctor_reports_unverified_protections():
    report = field.readiness()
    assert report["ready_for_autonomous_desktop_actions"] is False
    assert report["multi_account_access_restriction_field_verified"] is False
    assert report["user_task_verified"] is False


def test_probe_requires_real_windows_interactive_terminal(monkeypatch):
    called = []
    def request(*args):
        called.append(args)
        raise AssertionError("Unattended request should not happen")
    if os.name == "nt":
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
        code = "interactive_operator_required"
    else:
        code = "windows_only"
    expect(code, lambda: field.run_supervised(
        "local-address", ask=lambda _: "READ ONLY",
        secret_prompt=lambda _: "secret", requester=request,
    ))
    assert not called


def test_refused_terminal_phrase_produces_no_request(monkeypatch):
    if os.name != "nt":
        pytest.skip("needs Windows")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    calls = []
    expect("field_operator_declined", lambda: field.run_supervised(
        "local-address", ask=lambda _: "no",
        secret_prompt=lambda _: "private", requester=lambda *a: calls.append(a),
    ))
    assert calls == []


def test_readiness_cli_is_offline(capsys):
    assert field.main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ready_for_autonomous_desktop_actions"] is False


@pytest.mark.skipif(os.name != "nt", reason="real R6 pipe requires Windows")
def test_real_windows_r6_pipe_sequential_observations_are_read_only():
    """Actual Windows pipe, real ACL/SID checks, fake accessibility backend."""
    from threading import Thread

    from app.services.desktop_bridge import (
        AgentDesktopCLI, DesktopBridge, DesktopPolicy, LocalAudit,
    )
    from app.services.desktop_broker import LocalDesktopBroker
    from app.services.desktop_windows_restricted_ipc import WindowsRestrictedReadOnlyPipe

    addresses = iter(["salpha1", "sbeta2"])
    invoked = []

    def runner(argv):
        invoked.append(tuple(argv))
        if argv[0] != "snapshot":
            raise AssertionError("Unexpected mutating command")
        sid = next(addresses)
        return {
            "version": "2.5",
            "command": "snapshot",
            "ok": True,
            "data": {
                "app": "Calculator",
                "complete": True,
                "snapshot_id": sid,
                "tree": {
                    "role": "window",
                    "children": [{
                        "role": "button",
                        "ref_id": f"@{sid}:e7",
                        "name": "7",
                        "available_actions": ["Click"],
                    }],
                },
            },
        }

    bridge = DesktopBridge(
        DesktopPolicy(frozenset({"Calculator"}), enable_click=False),
        cli=AgentDesktopCLI(runner=runner),
        audit=LocalAudit(),
    )
    broker = LocalDesktopBroker(bridge, "Calculator")
    key = bytes(range(32))
    with WindowsRestrictedReadOnlyPipe(broker, key) as server:
        def process_requests():
            for _ in range(3):
                assert server.serve_one() is True

        worker = Thread(target=process_requests, daemon=True)
        worker.start()
        try:
            result = field.perform_probe(
                server.address,
                key.hex(),
                second_observation=True,
                between=lambda: True,
            )
        finally:
            worker.join(timeout=12)
            assert not worker.is_alive(), "Windows R6 pipe did not drain requests"

    assert result["observations_checked"] == 2
    assert result["distinct_snapshot_ids"] is True
    assert result["transport_identity_cryptographically_attested"] is False
    assert result["autonomous_execution_authorized"] is False
    assert [c[0] for c in invoked] == ["snapshot", "snapshot"]
