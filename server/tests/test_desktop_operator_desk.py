"""R3 headless tests for the local native operator desk."""
import json
import os
from pathlib import Path

import pytest

from app.services.desktop_inbox import ProposalError, ProposalInbox
from app.services.desktop_operator_desk import OperatorDeskModel, OperatorPolicy, main


def write_policy(path, apps=None):
    path.write_text(json.dumps({
        "version": 1,
        "apps": apps if apps is not None else {
            "Calculator": {"observe": True, "click": False},
        },
    }), encoding="utf-8")
    return path


@pytest.fixture
def desk(tmp_path):
    inbox = ProposalInbox(tmp_path / "private" / "inbox.db")
    policy = OperatorPolicy.load(write_policy(tmp_path / "policy.json"))
    return OperatorDeskModel(inbox, policy)


def propose(model, operation="observe", app="Calculator", hint=""):
    return model.inbox.submit(
        source="agentora", app=app, operation=operation,
        reason="Inspect the local calculator", target_hint=hint,
        ttl_seconds=900,
    )


def fails(code, callback):
    with pytest.raises(ProposalError) as exc:
        callback()
    assert exc.value.code == code


def test_policy_observation_review_only(desk):
    item = propose(desk)
    assert "ELIGIBLE FOR REVIEW" in desk.details(item["id"])
    assert desk.review(item["id"], item["digest"], "reviewed")["status"] == "reviewed"
    instructions = desk.handoff(item["id"])
    assert "No command was executed" in instructions


def test_click_policy_defaults_deny(desk):
    item = propose(desk, operation="click", hint="Digit 7")
    assert "POLICY DENIED" in desk.details(item["id"])
    fails("operation_policy_denied",
          lambda: desk.review(item["id"], item["digest"], "reviewed"))
    fails("operation_policy_denied", lambda: desk.handoff(item["id"]))
    assert desk.get(item["id"])["status"] == "pending"


def test_unknown_app_denied(desk):
    item = propose(desk, app="Password Manager")
    fails("operation_policy_denied",
          lambda: desk.review(item["id"], item["digest"], "reviewed"))


def test_reject_allowed_even_when_review_policy_denies(desk):
    item = propose(desk, app="Password Manager")
    assert desk.review(item["id"], item["digest"], "rejected")["status"] == "rejected"
    fails("manual_handoff_requires_review", lambda: desk.inbox.handoff(item["id"]))


def test_old_digest_cannot_change_state(desk):
    item = propose(desk)
    fails("proposal_changed_refresh_required",
          lambda: desk.review(item["id"], "0" * 64, "reviewed"))
    assert desk.get(item["id"])["status"] == "pending"


def test_one_time_review(desk):
    item = propose(desk)
    desk.review(item["id"], item["digest"], "reviewed")
    fails("proposal_stale_or_not_pending",
          lambda: desk.review(item["id"], item["digest"], "rejected"))


def test_no_executor_or_broker_in_controller(desk):
    assert not hasattr(desk, "execute")
    assert not hasattr(desk, "click")
    assert not hasattr(desk, "broker")
    item = propose(desk)
    assert desk.list()[0]["id"] == item["id"]


def test_listing_rechecks_digest(desk):
    item = propose(desk)
    with desk.inbox._connect() as conn:
        conn.execute(
            "UPDATE desktop_proposals SET payload=? WHERE id=?",
            (json.dumps({"tampered": True}), item["id"]),
        )
        conn.commit()
    fails("proposal_integrity_failed", lambda: desk.list())


def test_policy_uses_exact_app_names(desk):
    assert desk.policy.permits("Calculator", "observe") is True
    assert desk.policy.permits("calculator", "observe") is False
    assert desk.policy.permits("*", "observe") is False
    assert desk.policy.permits("Calculator", "click") is False


@pytest.mark.parametrize("value", [
    {"version": 1, "apps": {"Calculator": {"observe": True}}},
    {"version": 1, "apps": {"Calculator": {"observe": 1, "click": False}}},
    {"version": 1, "apps": {"Calculator": {"observe": True, "click": False, "shell": True}}},
    {"version": 2, "apps": {}},
    {"version": True, "apps": {}},
    {"version": 1, "apps": [], "extraneous": False},
    {"version": 1, "apps": []},
    {"version": 1, "apps": {" Bad ": {"observe": True, "click": False}}},
])
def test_policy_rejects_bad_schema(tmp_path, value):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value))
    fails("invalid_policy_schema", lambda: OperatorPolicy.load(path))


def test_policy_file_missing_or_oversized(tmp_path):
    fails("invalid_policy_file",
          lambda: OperatorPolicy.load(tmp_path / "not-found.json"))
    huge = tmp_path / "huge.json"
    huge.write_text("A" * 16400)
    fails("invalid_policy_file", lambda: OperatorPolicy.load(huge))


def test_symlink_policy_forbidden(tmp_path):
    policy = write_policy(tmp_path / "p.json")
    shortcut = tmp_path / "shortcut.json"
    try:
        shortcut.symlink_to(policy)
    except OSError:
        pytest.skip("symlink creation unavailable")
    fails("policy_symlink_forbidden", lambda: OperatorPolicy.load(shortcut))


def test_policy_must_be_explicit(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(tmp_path / "unused.db")])
    assert exc.value.code == 2


def test_explicit_click_review_does_not_execute(tmp_path):
    inbox = ProposalInbox(tmp_path / "private" / "inbox.db")
    policy = OperatorPolicy.load(write_policy(
        tmp_path / "policy.json",
        {"Calculator": {"observe": True, "click": True}},
    ))
    desk = OperatorDeskModel(inbox, policy)
    item = propose(desk, operation="click", hint="Digit 7")
    assert desk.review(item["id"], item["digest"], "reviewed")["status"] == "reviewed"
    instructions = desk.handoff(item["id"])
    assert "FRESH observation" in instructions
    assert "No command was executed" in instructions
    assert [e["status"] for e in inbox.events(item["id"])] == ["pending", "reviewed"]


def test_no_network_or_gui_required_to_test_model(desk, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("No network or execution allowed")
    monkeypatch.setattr("socket.create_connection", blocked)
    item = propose(desk)
    desk.review(item["id"], item["digest"], "reviewed")
    assert "MANUAL FOLLOW-UP ONLY" in desk.handoff(item["id"])
