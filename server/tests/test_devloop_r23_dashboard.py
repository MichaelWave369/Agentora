"""R2.3 dashboard: exact GitHub merge verification and no autonomous writes."""
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devloop_r23_dashboard as dashboard

SHA = "a" * 40
MERGE_SHA = "b" * 40


def zip_receipt(name, data):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, json.dumps(data))
    return buffer.getvalue()


def merge_receipt(**updates):
    data = {
        "schema": dashboard.SCHEMAS["merge"],
        "pr_number": 59,
        "head_sha": SHA,
        "lane": "solo",
        "event_action": "labeled",
        "source": "trusted-main-github-actions",
        "disposition": "SUCCESS",
        "decision": "R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED",
    }
    data.update(updates)
    return data


def merged_pr(actor="github-actions[bot]", sha=SHA, merge_sha=MERGE_SHA):
    return {
        "number": 59,
        "state": "closed",
        "merged": True,
        "merged_by": {"login": actor},
        "merge_commit_sha": merge_sha,
        "head": {"sha": sha},
        "base": {"ref": "main"},
    }


def fake_api(token, path):
    if path.endswith("/pulls/59"):
        return merged_pr()
    raise AssertionError("Unexpected API path: " + path)


def test_zip_unpacking_only_accepts_bounded_unique_json():
    payload = merge_receipt()
    blob = zip_receipt("merge-decision.json", payload)
    assert dashboard.extract_json(blob, "merge-decision.json") == payload

    with pytest.raises(dashboard.DashboardHeld, match="R23_ARCHIVE_TOO_LARGE"):
        dashboard.extract_json(b"x" * (dashboard.MAX_ZIP_BYTES + 1), "merge-decision.json")
    with pytest.raises(dashboard.DashboardHeld, match="R23_ARCHIVE_INVALID"):
        dashboard.extract_json(b"definitely not a ZIP", "merge-decision.json")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("merge-decision.json", json.dumps(payload))
        archive.writestr("alternate/merge-decision.json", "{}")
    with pytest.raises(dashboard.DashboardHeld, match="NOT_UNIQUE"):
        dashboard.extract_json(buffer.getvalue(), "merge-decision.json")

    zip_slip = zip_receipt("../merge-decision.json", payload)
    with pytest.raises(dashboard.DashboardHeld, match="ARCHIVE_PATH"):
        dashboard.extract_json(zip_slip, "merge-decision.json")

    too_big = zip_receipt("merge-decision.json", {"blob": "z" * (dashboard.MAX_JSON_BYTES + 1)})
    with pytest.raises(dashboard.DashboardHeld, match="TOO_LARGE"):
        dashboard.extract_json(too_big, "merge-decision.json")


def test_only_exact_head_github_actions_attribution_confirms_bot_merge():
    run = {"id": 99}
    good = dashboard.interpret_receipt(fake_api, "t", "merge", run, merge_receipt())
    assert good["verification"] == "VERIFIED_BOT_MERGE"
    assert good["lane"] == "solo"

    def manual(token, path):
        return merged_pr(actor="MichaelWave369")
    out = dashboard.interpret_receipt(manual, "t", "merge", run, merge_receipt())
    assert out["verification"] == "MERGED_BY_OTHER_ACTOR"

    def wrong_sha(token, path):
        return merged_pr(sha="c" * 40)
    out = dashboard.interpret_receipt(wrong_sha, "t", "merge", run, merge_receipt())
    assert out["verification"] == "PR_IDENTITY_MISMATCH"

    held = dashboard.interpret_receipt(
        fake_api, "t", "merge", run, merge_receipt(
            disposition="HELD", decision="R21_REQUIRED_CHECK_NOT_GREEN"))
    assert held["verification"] == "HELD_DECISION_ONLY"

    unknown = dashboard.interpret_receipt(
        fake_api, "t", "merge", run, merge_receipt(
            disposition="SUCCESS", decision="SOME_UNVERIFIED_SUCCESS_STRING"))
    assert unknown["verification"] == "UNRECOGNIZED_MERGE_DECISION"


def test_refuse_malformed_merge_receipts_and_forged_success():
    for payload in (
        merge_receipt(pr_number="59"),
        merge_receipt(head_sha="not-sha"),
        merge_receipt(disposition=None),
        merge_receipt(schema="untrusted"),
    ):
        with pytest.raises(dashboard.DashboardHeld):
            dashboard.interpret_receipt(fake_api, "t", "merge", {"id": 1}, payload)


def test_handoff_is_read_only_even_when_ready_for_operator():
    receipt = {
        "schema": dashboard.SCHEMAS["handoff"],
        "source_pr": 59,
        "source_head_sha": SHA,
        "merge_commit_sha": MERGE_SHA,
        "disposition": "READY_FOR_OPERATOR_DISPATCH",
        "task_id": "next-rung-123",
        "executable": False,
    }
    row = dashboard.interpret_receipt(fake_api, "t", "handoff", {"id": 1}, receipt)
    assert row["decision"] == "READY_FOR_OPERATOR_DISPATCH"
    assert row["verification"] == "BOT_MERGE_VERIFIED"
    assert row["executable"] is False
    invalid = dict(receipt, executable=True)
    with pytest.raises(dashboard.DashboardHeld, match="EXECUTABLE"):
        dashboard.interpret_receipt(fake_api, "t", "handoff", {"id": 1}, invalid)
    missing = dict(receipt, merge_commit_sha="c" * 40)
    wrong = dashboard.interpret_receipt(fake_api, "t", "handoff", {"id": 1}, missing)
    assert wrong["verification"] == "SOURCE_MERGE_SHA_MISMATCH"


def test_queue_receipts_never_approve_any_merge():
    payload = {
        "schema": dashboard.SCHEMAS["queue"],
        "mode": "READ_ONLY_ADVISORY_NOT_MERGE_AUTHORITY",
        "can_merge": False, "rows": [],
        "open_pr_count": 0,
    }
    good = dashboard.interpret_receipt(fake_api, "t", "queue", {"id": 1}, payload)
    assert good["verification"] == "RECEIPT_READ_ONLY"
    with pytest.raises(dashboard.DashboardHeld, match="CLAIMS_AUTHORITY"):
        dashboard.interpret_receipt(fake_api, "t", "queue", {"id": 1},
                                    dict(payload, can_merge=True))


def test_artifact_selection_is_exact_and_expiry_holds():
    run_id = 4127
    def get(token, path):
        return {"total_count": 1, "artifacts": [{
            "id": 456, "size_in_bytes": 1000, "expired": False,
            "name": f"devloop-merge-decision-59-{run_id}"}]}
    assert dashboard.find_receipt_artifact(get, "t", run_id, "merge") == 456

    def missing(token, path):
        return {"total_count": 0, "artifacts": []}
    with pytest.raises(dashboard.DashboardHeld, match="MISSING"):
        dashboard.find_receipt_artifact(missing, "t", run_id, "merge")

    def many(token, path):
        return {"total_count": 100, "artifacts": []}
    with pytest.raises(dashboard.DashboardHeld, match="INCOMPLETE"):
        dashboard.find_receipt_artifact(many, "t", run_id, "merge")

    def expired(token, path):
        return {"total_count": 1, "artifacts": [{
            "id": 456, "size_in_bytes": 1000, "expired": True,
            "name": f"devloop-merge-decision-59-{run_id}"}]}
    with pytest.raises(dashboard.DashboardHeld, match="EXPIRED"):
        dashboard.find_receipt_artifact(expired, "t", run_id, "merge")


def test_recent_workflow_is_bounded_to_allowlist():
    assert dashboard.read_recent_runs(
        lambda t, p: {"workflow_runs": [{"id": 1}]},
        "t", "devloop-automerge.yml", 12) == [{"id": 1}]
    with pytest.raises(dashboard.DashboardHeld, match="INVALID_WORKFLOW"):
        dashboard.read_recent_runs(lambda t, p: {}, "t", "attacker.yml", 12)


def test_history_holds_missing_artifact_and_never_calls_merge():
    accesses = []
    def get(token, path):
        accesses.append(path)
        if "/actions/workflows/" in path:
            return {"workflow_runs": [{"id": 10, "status": "completed",
                                       "conclusion": "success"}]}
        if "/actions/runs/10/artifacts" in path:
            return {"total_count": 0, "artifacts": []}
        raise AssertionError(path)
    rows = dashboard.history(get, lambda t, a: b"", "token", "merge")
    assert len(rows) == 1
    assert rows[0]["verification"] == "EVIDENCE_HELD"
    assert not any("/merge" in path for path in accesses)
    assert not any("/labels" in path for path in accesses)


def test_full_assembly_does_not_promote_queue_to_authorization(monkeypatch):
    import devloop_r23_dashboard as d
    monkeypatch.setattr(d, "queue_snapshot", lambda get, token: {
        "open_pr_count": 0, "rows": [], "can_merge": False,
    })
    monkeypatch.setattr(d, "history", lambda get, fetch, token, kind: (
        [{"verification": "VERIFIED_BOT_MERGE"}] if kind == "merge" else
        [{"verification": "BOT_MERGE_VERIFIED",
          "decision": "NO_PREAPPROVED_NEXT_RUNG"}] if kind == "handoff" else []
    ))
    result = d.assemble(lambda t, p: None, lambda t, a: b"", "token")
    assert result["can_merge"] is False
    assert result["can_dispatch"] is False
    assert result["metrics"]["verified_bot_merges"] == 1
    assert result["metrics"]["no_preapproved_next_rung"] == 1
    report = d.markdown_report(result)
    assert "Verified automated merges" in report
    assert "Handoffs" in report or "handoffs" in report
    assert "read-only" in report.lower()


def test_failed_dashboard_does_not_print_empty_queue_as_if_verified():
    failed = dashboard.markdown_report({
        "error": "R23_GITHUB_UNAVAILABLE",
        "captured_utc": "2026-10-31T00:00:00Z",
    })
    assert "DASHBOARD HELD" in failed
    assert "No open PRs" not in failed
