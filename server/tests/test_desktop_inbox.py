"""R2 proposal-inbox contract: no OS/desktop access, with concurrency guards."""
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.desktop_inbox import (
    MAX_PENDING, ProposalError, ProposalInbox, main, normalize_proposal,
    submit_agentora_proposal,
)


@pytest.fixture
def setup(tmp_path):
    now = [1_800_000_000]
    inbox = ProposalInbox(tmp_path / "local-only" / "inbox.db", clock=lambda: now[0])
    return inbox, now


def propose(inbox, **overrides):
    args = dict(source="agentora", app="Calculator", operation="observe",
                reason="Check the calculator display", ttl_seconds=300)
    args.update(overrides)
    return inbox.submit(**args)


def fails(code, callback):
    with pytest.raises(ProposalError) as exc:
        callback()
    assert exc.value.code == code


def test_default_proposal_is_not_executable(setup):
    inbox, _ = setup
    item = propose(inbox)
    assert item["status"] == "pending"
    assert not hasattr(inbox, "execute")
    assert not hasattr(inbox, "approve")
    assert inbox.list()[0]["id"] == item["id"]
    assert inbox.get(item["id"])["proposal"]["source"] == "agentora"


def test_agentora_adapter_records_correlation_without_action_execution(setup):
    inbox, _ = setup
    item = submit_agentora_proposal(inbox, run_id=22, app="Calculator",
                                   operation="click", reason="Select number seven",
                                   target_hint="Digit 7")
    assert item["proposal"]["correlation_id"] == "run:22"
    assert item["proposal"]["target_hint"] == "Digit 7"
    fails("invalid_run_id", lambda: submit_agentora_proposal(
        inbox, run_id=-1, app="Calculator", operation="observe", reason="Inspect"
    ))


@pytest.mark.parametrize("kwargs,code", [
    ({"source": "../bad"}, "invalid_source"),
    ({"app": "Bad\nName"}, "invalid_app"),
    ({"operation": "shell"}, "invalid_operation"),
    ({"reason": ""}, "invalid_reason"),
    ({"operation": "click", "target_hint": ""}, "invalid_target_hint"),
    ({"operation": "click", "target_hint": "@sabc123:e7"}, "stale_snapshot_ref_forbidden"),
    ({"ttl_seconds": 900000}, "invalid_ttl"),
    ({"correlation_id": "../secret"}, "invalid_correlation_id"),
])
def test_bad_intents_never_enter_store(setup, kwargs, code):
    inbox, _ = setup
    fails(code, lambda: propose(inbox, **kwargs))
    assert inbox.list(status="all") == []


def test_unknown_keyword_rejected():
    with pytest.raises(TypeError):
        normalize_proposal(
            source="agentora", app="Calculator", operation="observe",
            reason="Inspect", secret="not_allowed",
        )


def test_review_records_decision_without_dispatch(setup):
    inbox, _ = setup
    item = propose(inbox)
    reviewed = inbox.review(item["id"], item["digest"], "reviewed")
    assert reviewed["status"] == "reviewed"
    assert "No command was executed" in inbox.handoff(item["id"])
    assert [e["status"] for e in inbox.events(item["id"])] == ["pending", "reviewed"]
    fails("proposal_stale_or_not_pending",
          lambda: inbox.review(item["id"], item["digest"], "rejected"))


def test_rejected_intent_cannot_be_handed_off(setup):
    inbox, _ = setup
    item = propose(inbox)
    inbox.review(item["id"], item["digest"], "rejected")
    fails("manual_handoff_requires_review", lambda: inbox.handoff(item["id"]))


def test_wrong_digest_never_changes_state(setup):
    inbox, _ = setup
    item = propose(inbox)
    fails("proposal_stale_or_not_pending",
          lambda: inbox.review(item["id"], "0" * 64, "reviewed"))
    assert inbox.get(item["id"])["status"] == "pending"


def test_automatic_expiry_prevents_late_review(setup):
    inbox, now = setup
    item = propose(inbox, ttl_seconds=30)
    now[0] += 31
    assert inbox.get(item["id"])["status"] == "expired"
    fails("proposal_stale_or_not_pending",
          lambda: inbox.review(item["id"], item["digest"], "reviewed"))
    assert [e["status"] for e in inbox.events(item["id"])] == ["pending", "expired"]


def test_read_only_list_does_not_leak_executable_grant(setup):
    inbox, _ = setup
    item = propose(inbox, operation="click", target_hint="Digit 7")
    record = inbox.list(status="all")[0]
    assert record["id"] == item["id"]
    assert "token" not in record["proposal"]
    assert "ref" not in record["proposal"]
    assert record["status"] == "pending"


def test_same_proposal_cannot_be_reviewed_twice_concurrently(setup):
    inbox, _ = setup
    item = propose(inbox)
    def review(decision):
        try:
            inbox.review(item["id"], item["digest"], decision)
            return "changed"
        except ProposalError as exc:
            return exc.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(review, ["reviewed", "rejected"]))
    assert sorted(results) == ["changed", "proposal_stale_or_not_pending"]
    assert len(inbox.events(item["id"])) == 2


def test_inbox_cap_prevents_unbounded_pending_growth(setup):
    inbox, _ = setup
    for _ in range(MAX_PENDING):
        propose(inbox)
    fails("inbox_pending_limit", lambda: propose(inbox))


def test_local_metadata_events_exclude_payload(setup):
    inbox, _ = setup
    item = propose(inbox, reason="Private example request")
    serialized = json.dumps(inbox.events(item["id"]))
    assert "Private example" not in serialized
    assert "Calculator" not in serialized


def test_cli_review_requires_real_terminal(setup, capsys):
    inbox, _ = setup
    item = propose(inbox)
    rc = main(["--db", str(inbox.path), "review", item["id"], "--decision", "reviewed"])
    assert rc == 2
    assert "interactive_operator_required" in capsys.readouterr().err
    assert inbox.get(item["id"])["status"] == "pending"


def test_cli_review_cancel_is_noop(setup, monkeypatch):
    inbox, _ = setup
    item = propose(inbox)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "cancel")
    assert main(["--db", str(inbox.path), "review", item["id"], "--decision", "reviewed"]) == 2
    assert inbox.get(item["id"])["status"] == "pending"


def test_cli_review_explicit_challenge_changes_only_status(setup, monkeypatch, capsys):
    inbox, _ = setup
    item = propose(inbox)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr("app.services.desktop_inbox.secrets.token_hex", lambda _: "cafe1234")
    monkeypatch.setattr("builtins.input", lambda _: "REVIEW cafe1234")
    assert main(["--db", str(inbox.path), "review", item["id"], "--decision", "reviewed"]) == 0
    assert inbox.get(item["id"])["status"] == "reviewed"
    assert "No desktop action was performed" in capsys.readouterr().out


def test_reject_symlink_store(tmp_path):
    target = tmp_path / "target.db"
    target.write_text("not a database")
    alias = tmp_path / "link.db"
    try:
        alias.symlink_to(target)
    except OSError:
        pytest.skip("symlinks disabled")
    fails("symlink_inbox_forbidden", lambda: ProposalInbox(alias))


def test_secure_posix_file_mode(setup):
    inbox, _ = setup
    if os.name == "posix":
        assert inbox.path.stat().st_mode & 0o077 == 0


def test_manual_handoff_never_uses_snapshot_ref(setup):
    inbox, _ = setup
    item = propose(inbox, operation="click", target_hint="Digit 7")
    inbox.review(item["id"], item["digest"], "reviewed")
    message = inbox.handoff(item["id"])
    assert "FRESH observation" in message
    assert "No command was executed" in message
    assert "@s" not in message
