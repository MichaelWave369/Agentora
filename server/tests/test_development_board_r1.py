"""R1-A: exact-commit local GitPorch + PhiBot review-only handoff."""
from copy import deepcopy
from unittest.mock import patch

from app.services.development_board.r1_handoff import (
    fetch_local_gitporch, inspect_gitporch, inspect_phibot, preview_handoff,
)
from .conftest import make_client

SHA = "a" * 40
OTHER_SHA = "b" * 40
HEALTH = "LOCAL_RECEIPTS_CHECKED_NOT_ATTESTED"


def _gitporch():
    return {
        "service": "PhiRunners", "version": "R1-E", "mode": "LOCAL_READ_ONLY",
        "health": HEALTH,
        "lanes": {
            "git": {"jobType": "GIT_OBJECT_INTEGRITY", "health": HEALTH},
            "tests": {"jobType": "NODE_BUILTIN_TESTS", "health": HEALTH},
        },
        "jobs": [
            {"id": "001", "lane": "git", "repo": "Disposable", "commit": SHA, "status": "DONE", "outcome": "PASS"},
            {"id": "002", "lane": "tests", "repo": "Disposable", "commit": SHA, "status": "DONE", "outcome": "PASS"},
        ],
    }


def _phibot():
    return {
        "schema": "phibot.repo-verification.v1", "mode": "READ_ONLY_NO_PROMOTION",
        "observedAt": "2026-10-27T20:00:00.000Z",
        "repositories": [
            {"repository": "MichaelWave369/Disposable", "candidates": [
                {"pr": 7, "headSha": SHA, "status": "CHECKS_PASS_REVIEW_ONLY",
                 "checkStatus": "CHECKS_PASS_REVIEW_ONLY",
                 "evidence": [{"name": "test", "origin": "check_run",
                               "status": "completed", "conclusion": "success"}]},
            ]},
        ],
    }


def _payload():
    return {"local_repo": "Disposable", "github_repo": "MichaelWave369/Disposable",
            "pr_number": 7, "commit_sha": SHA, "gitporch": _gitporch(), "phibot": _phibot()}


def test_review_ready_is_never_merge_permission():
    result = preview_handoff(_payload())
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED"
    assert result["eligible_for_merge"] is False
    assert result["automatic_merge"] is False
    assert result["verifier_identity_authenticated"] is False
    assert result["operator_approval_authenticated"] is False
    assert result["gitporch"]["source_attested"] is False
    assert result["phibot"]["source_attested"] is False


def test_gitporch_wrong_commit_refuses():
    payload = _payload()
    payload["gitporch"]["jobs"][0]["commit"] = OTHER_SHA
    result = preview_handoff(payload)
    assert result["status"] == "HELD"
    assert "MISSING_EXACT_SHA_GIT_JOB" in result["gitporch"]["reasons"]


def test_gitporch_missing_node_test_does_not_confuse_fsck_with_ci():
    payload = _payload()
    payload["gitporch"]["jobs"].pop()
    result = preview_handoff(payload)
    assert "MISSING_EXACT_SHA_TESTS_JOB" in result["gitporch"]["reasons"]


def test_gitporch_newer_failed_job_overrides_older_pass():
    payload = _payload()
    payload["gitporch"]["jobs"].append({
        "id": "003", "lane": "tests", "repo": "Disposable",
        "commit": SHA, "status": "DONE", "outcome": "FAIL",
    })
    result = preview_handoff(payload)
    assert "TESTS_LATEST_JOB_NOT_PASSING" in result["gitporch"]["reasons"]


def test_gitporch_duplicate_job_id_refuses():
    payload = _payload()
    payload["gitporch"]["jobs"].append(deepcopy(payload["gitporch"]["jobs"][1]))
    assert "DUPLICATE_TESTS_JOB_ID" in preview_handoff(payload)["gitporch"]["reasons"]


def test_partial_gitporch_snapshot_never_appears_green():
    payload = _payload()
    payload["gitporch"]["health"] = "PARTIAL_OR_UNVERIFIED"
    assert "GITPORCH_SNAPSHOT_UNVERIFIED" in preview_handoff(payload)["gitporch"]["reasons"]


def test_phibot_stale_sha_or_wrong_pr_never_green():
    payload = _payload()
    payload["phibot"]["repositories"][0]["candidates"][0]["headSha"] = OTHER_SHA
    assert "PHIBOT_SHA_MISMATCH" in preview_handoff(payload)["phibot"]["reasons"]
    payload = _payload()
    payload["pr_number"] = 9
    assert "PHIBOT_PR_MISSING_OR_AMBIGUOUS" in preview_handoff(payload)["phibot"]["reasons"]


def test_phibot_truncated_ambiguous_or_failed_checks_refuse():
    payload = _payload()
    payload["phibot"]["repositories"][0]["candidates"].append(
        deepcopy(payload["phibot"]["repositories"][0]["candidates"][0])
    )
    assert "PHIBOT_PR_MISSING_OR_AMBIGUOUS" in preview_handoff(payload)["phibot"]["reasons"]
    payload = _payload()
    payload["phibot"]["repositories"][0]["candidates"][0]["evidence"][0]["conclusion"] = "failure"
    assert "PHIBOT_CHECK_NOT_SUCCESS" in preview_handoff(payload)["phibot"]["reasons"]
    payload = _payload()
    payload["phibot"]["repositories"][0]["candidates"][0]["status"] = "CHECKS_PENDING"
    assert "PHIBOT_CHECKS_NOT_PASSING" in preview_handoff(payload)["phibot"]["reasons"]


def test_forged_extra_approval_does_not_grant_merge():
    payload = _payload()
    payload["operator_approved"] = True
    payload["merge_grant"] = "signed"
    payload["phibot"]["independent_attestation"] = True
    result = preview_handoff(payload)
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED"
    assert result["eligible_for_merge"] is False


def test_bad_types_hold_instead_of_crashing():
    payload = _payload()
    payload.update(local_repo=42, github_repo=[], pr_number=True, commit_sha=42)
    result = preview_handoff(payload)
    assert result["status"] == "HELD"
    assert result["eligible_for_merge"] is False
    assert inspect_gitporch(None, "Disposable", SHA)["status"] == "HELD"
    assert inspect_phibot(None, "MichaelWave369/Disposable", 7, SHA)["status"] == "HELD"
    assert preview_handoff({"untrusted": "x" * 150000})["reasons"] == ["IMPORT_TOO_LARGE"]


def test_local_reader_default_disabled_does_not_contact_network(monkeypatch):
    monkeypatch.delenv("AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED", raising=False)
    with patch("requests.Session") as session:
        result = fetch_local_gitporch()
    assert result["connection"] == "DISABLED"
    session.assert_not_called()


def test_local_reader_bad_port_never_contacts_network(monkeypatch):
    monkeypatch.setenv("AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED", "1")
    monkeypatch.setenv("AGENTORA_DEVBOARD_GITPORCH_PORT", "3690.evil.com")
    with patch("requests.Session") as session:
        result = fetch_local_gitporch()
    assert result["reason"] == "INVALID_GITPORCH_PORT"
    session.assert_not_called()


def test_local_reader_only_fixed_loopback_get(monkeypatch):
    monkeypatch.setenv("AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED", "1")
    monkeypatch.setenv("AGENTORA_DEVBOARD_GITPORCH_PORT", "3690")
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.headers = {"Content-Type": "application/json; charset=utf-8"}
    import json
    response.iter_content.return_value = [json.dumps(_gitporch()).encode()]
    session = MagicMock()
    session.get.return_value = response
    with patch("requests.Session", return_value=session):
        result = fetch_local_gitporch()
    assert result["connection"] == "LOCAL_SELF_REPORTED"
    assert session.trust_env is False
    assert session.get.call_args.args[0] == "http://127.0.0.1:3690/api/phirunners"
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["stream"] is True


def test_local_reader_oversized_response_fails(monkeypatch):
    monkeypatch.setenv("AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED", "true")
    from unittest.mock import MagicMock
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = 200
    response.headers = {"Content-Type": "application/json"}
    response.iter_content.return_value = [b"x" * (128 * 1024 + 1)]
    session = MagicMock()
    session.get.return_value = response
    with patch("requests.Session", return_value=session):
        assert fetch_local_gitporch()["reason"] == "RESPONSE_TOO_LARGE"


def test_review_only_api_returns_no_authority():
    client = make_client()
    r = client.post("/api/development-board/handoff/preview", json=_payload())
    assert r.status_code == 200
    assert r.json()["status"] == "REVIEW_READY_NOT_AUTHORIZED"
    assert r.json()["eligible_for_merge"] is False
