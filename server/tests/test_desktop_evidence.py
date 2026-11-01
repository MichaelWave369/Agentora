"""R4 isolated evidence tests: do not invoke a real desktop or broker."""
import json
import sys

import pytest

from app.services.desktop_bridge import (
    DesktopBridgeError, DesktopPolicy, Observation, Target,
)
from app.services.desktop_evidence import (
    EvidenceRule, assess, doctor, main, supervised_trial,
)


def observation(sid: str, tick: float, *names: str, app: str = "Calculator"):
    targets = {
        f"@{sid}:e{i}": Target(
            ref=f"@{sid}:e{i}", role="button", name=name, actions=frozenset({"Click"})
        ) for i, name in enumerate(names)
    }
    return Observation(app=app, snapshot_id=sid, targets=targets, captured_at=tick)


def test_appears_supports_only_narrow_accessibility_change():
    result = assess(
        observation("s1", 20, "AC"),
        observation("s2", 21, "AC", "OK"),
        EvidenceRule("button", "OK", "appeared"),
        now=22,
    )
    assert result.status == "supporting_observation"
    assert result.reason == "expected_change_observed"
    receipt = result.receipt()
    assert receipt["task_verified"] is False
    assert receipt["desktop_action_executed_by_this_tool"] is False
    assert receipt["pre_match_count"] == 0
    assert receipt["post_match_count"] == 1
    assert "OK" not in json.dumps(receipt)
    assert "Calculator" not in json.dumps(receipt)
    assert "@s2" not in json.dumps(receipt)


def test_disappeared_exactly_once():
    result = assess(
        observation("s1", 10, "OK"),
        observation("s2", 11, "Cancel"),
        EvidenceRule("button", "OK", "disappeared"),
        now=12,
    )
    assert result.status == "supporting_observation"


def test_unchanged_is_not_claimed_as_success():
    result = assess(
        observation("s1", 10, "OK"),
        observation("s2", 11, "OK"),
        EvidenceRule("button", "OK", "disappeared"),
        now=12,
    )
    assert result.status == "contradicting_observation"
    assert result.reason == "expected_change_not_observed"


def test_same_snapshot_is_inconclusive_even_if_labels_change():
    result = assess(
        observation("s1", 10),
        observation("s1", 11, "OK"),
        EvidenceRule("button", "OK", "appeared"),
        now=12,
    )
    assert result.status == "inconclusive"
    assert result.reason == "not_independent_snapshots"


def test_changed_app_is_inconclusive():
    result = assess(
        observation("s1", 10),
        observation("s2", 11, "OK", app="Other"),
        EvidenceRule("button", "OK", "appeared"),
        now=12,
    )
    assert result.reason == "app_changed"


def test_stale_or_future_snapshots_fail_closed():
    rule = EvidenceRule("button", "OK", "appeared")
    a = observation("s1", 1)
    b = observation("s2", 3, "OK")
    assert assess(a, b, rule, now=500).reason == "snapshot_out_of_window"
    assert assess(a, b, rule, now=2).reason == "snapshot_out_of_window"


def test_duplicate_role_name_is_ambiguous():
    before = observation("s1", 10)
    after = observation("s2", 11, "OK", "OK")
    result = assess(before, after, EvidenceRule("button", "OK", "appeared"), now=12)
    assert result.reason == "ambiguous_duplicate_matches"
    assert result.status == "inconclusive"


@pytest.mark.parametrize("kwargs,code", [
    ({"role": ""}, "invalid_role"),
    ({"name": " "}, "invalid_name"),
    ({"name": "secret\ninput"}, "invalid_name"),
    ({"transition": "executed"}, "invalid_transition"),
    ({"role": "a" * 81}, "invalid_role"),
    ({"name": "a" * 121}, "invalid_name"),
])
def test_rules_fail_closed(kwargs, code):
    options = {"role": "button", "name": "OK", "transition": "appeared"}
    options.update(kwargs)
    with pytest.raises(DesktopBridgeError) as info:
        EvidenceRule(**options)
    assert info.value.code == code


class FakeBridge:
    def __init__(self, observations, click=False):
        self.policy = DesktopPolicy(frozenset({"Calculator"}), enable_click=click)
        self.observations = list(observations)
        self.calls = []

    def observe(self, app):
        self.calls.append(("observe", app))
        return self.observations.pop(0)


def test_trial_refuses_to_operate_from_ci(monkeypatch):
    bridge = FakeBridge([
        observation("s1", 20), observation("s2", 21, "OK"),
    ])
    with pytest.raises(DesktopBridgeError) as info:
        supervised_trial("Calculator", EvidenceRule("button", "OK", "appeared"),
                         bridge=bridge, confirm=lambda _: "START")
    assert info.value.code == "interactive_operator_required"
    assert bridge.calls == []


def test_trial_does_not_execute_any_action(monkeypatch):
    import time
    tick = time.monotonic()
    bridge = FakeBridge([
        observation("s1", tick - 2),
        observation("s2", tick - 1, "OK"),
    ])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    replies = iter(["START", "CAPTURE"])
    result = supervised_trial(
        "Calculator", EvidenceRule("button", "OK", "appeared"),
        bridge=bridge, confirm=lambda _: next(replies),
    )
    assert result.status == "supporting_observation"
    assert bridge.calls == [("observe", "Calculator"), ("observe", "Calculator")]


def test_trial_rejects_write_enabled_bridge(monkeypatch):
    bridge = FakeBridge([], click=True)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with pytest.raises(DesktopBridgeError) as info:
        supervised_trial("Calculator", EvidenceRule("button", "OK", "appeared"),
                         bridge=bridge, confirm=lambda _: "START")
    assert info.value.code == "read_only_bridge_required"
    assert bridge.calls == []


def test_operator_decline_blocks_observation(monkeypatch):
    bridge = FakeBridge([])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with pytest.raises(DesktopBridgeError) as info:
        supervised_trial("Calculator", EvidenceRule("button", "OK", "appeared"),
                         bridge=bridge, confirm=lambda _: "CANCEL")
    assert info.value.code == "operator_declined"
    assert bridge.calls == []


def test_doctor_is_explicit_about_missing_security_features():
    report = doctor()
    assert report["os_level_ipc_isolation"] == "not_implemented"
    assert report["windows_acl_hardening"] == "not_implemented"
    assert report["local_trial_mode"] == "observation_only"


def test_doctor_cli_does_not_touch_real_desktop(capsys):
    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema"] == 1
    assert report["local_trial_mode"] == "observation_only"
