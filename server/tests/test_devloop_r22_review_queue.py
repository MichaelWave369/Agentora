"""R2.2 read-only queue refuses incomplete evidence and never grants authority."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devloop_r22_review_queue as q

SHA = "a" * 40


def sample_pr(*, author="MichaelWave369", labels=(), number=81):
    return {
        "number": number, "state": "open", "draft": False,
        "title": "Small test", "changed_files": 1,
        "user": {"login": author},
        "head": {"sha": SHA, "repo": {"full_name": q.REPO}},
        "base": {"ref": "main", "repo": {"full_name": q.REPO}},
        "labels": [{"name": name} for name in labels],
    }


def nav_file(additions=1, deletions=1):
    return [{
        "filename": "web/src/components/Nav.tsx", "status": "modified",
        "additions": additions, "deletions": deletions,
        "patch": "@@ -1,2 +1,2 @@\n-old\n+new",
    }]


def green_check_runs():
    checks = [
        {"name": name, "app": {"slug": "github-actions"},
         "status": "completed", "conclusion": "success"} for name in q.REQUIRED
    ]
    return {"total_count": len(checks), "check_runs": checks}


def test_solo_candidate_is_advisory_only_and_requires_owner_review():
    row = q.evaluate(
        sample_pr(), nav_file(), q.check_summary(
            lambda token, path: green_check_runs(), "t", SHA), True,
    )
    assert row["lane"] == "solo"
    assert row["status"] == "OWNER_REVIEW_REQUIRED"
    assert "phi-solo-automerge" in row["next_action"]
    assert row["merge_authorized"] is False
    assert row["authorization_granted"] is False


def test_owner_applied_label_does_not_mark_queue_as_merge_permission():
    row = q.evaluate(
        sample_pr(labels=("phi-solo-automerge",)), nav_file(),
        {"state": "GREEN", "checks": {}}, True,
    )
    assert row["status"] == "AUTHORIZED_EVENT_PENDING"
    assert "governance" in row["next_action"]
    assert row["merge_authorized"] is False


@pytest.mark.parametrize("names,expected", [
    (("hold",), "HELD"),
    (("phi-solo-automerge", "phi-automerge"), "HELD"),
    (("security-review",), "HELD"),
])
def test_conflicts_are_never_presented_as_eligible(names, expected):
    row = q.evaluate(sample_pr(labels=names), nav_file(), {"state": "GREEN"}, True)
    assert row["status"] == expected


def test_pending_and_failed_ci_block_advisory_next_action():
    for state in ("PENDING", "FAILED", "MISSING", "UNVERIFIED"):
        row = q.evaluate(sample_pr(), nav_file(), {"state": state}, True)
        assert row["status"] == "CI_" + state
        assert "Do not" not in row["next_action"] or "authorize" in row["next_action"].lower()


def test_unverified_rules_take_precedence_over_green():
    row = q.evaluate(sample_pr(), nav_file(), {"state": "GREEN"}, False)
    assert row["status"] == "RULES_UNVERIFIED"


def test_scope_limits_docs_and_code():
    docs = [{"filename": "docs/guide.md", "status": "added"}]
    assert q.classify_candidate(sample_pr(), docs)[0] == "docs"
    assert q.classify_candidate(sample_pr(), nav_file())[0] == "solo"
    assert q.classify_candidate(sample_pr(author="someone-else"), nav_file())[0] == "reviewed"
    assert q.classify_candidate(sample_pr(), nav_file(additions=17))[0] == "reviewed"
    assert q.classify_candidate(sample_pr(), [
        {"filename": ".github/workflows/ci.yml", "status": "modified",
         "additions": 1, "deletions": 1, "patch": "@@ -1 +1 @@"}
    ])[0] == "manual"
    assert q.classify_candidate(sample_pr(), [
        {"filename": "docs/../scripts/malicious.md", "status": "added"}
    ])[0] == "manual"


def test_reviewed_ui_stays_review_required_without_independent_evidence():
    row = q.evaluate(sample_pr(author="someone-else"), nav_file(), {
        "state": "GREEN"}, True, review={"status": "NOT_VERIFIED"})
    assert row["status"] == "REVIEW_REQUIRED"
    assert row["merge_authorized"] is False


def test_check_reads_require_exact_complete_source_and_all_green():
    valid = q.check_summary(lambda token, path: green_check_runs(), "t", SHA)
    assert valid["state"] == "GREEN"
    bad = green_check_runs()
    bad["check_runs"][0]["status"] = "in_progress"
    assert q.check_summary(lambda t, p: bad, "t", SHA)["state"] == "PENDING"
    bad["check_runs"][0]["status"] = "completed"
    bad["check_runs"][0]["conclusion"] = "failure"
    assert q.check_summary(lambda t, p: bad, "t", SHA)["state"] == "FAILED"
    bad["check_runs"][0]["app"] = {"slug": "untrusted"}
    assert q.check_summary(lambda t, p: bad, "t", SHA)["state"] == "UNVERIFIED"
    malformed = {"total_count": 101, "check_runs": []}
    assert q.check_summary(lambda t, p: malformed, "t", SHA)["state"] == "UNVERIFIED"


def test_main_rules_are_read_and_required_names_exact():
    rules = [{
        "id": 42, "enforcement": "active",
    }]
    detail = {
        "target": "branch", "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
        "rules": [{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": name} for name in q.REQUIRED],
        }}],
    }
    def get(token, path):
        return detail if path.endswith("/rulesets/42") else rules
    assert q.verify_main_rules(get, "t") is True
    detail["rules"][0]["parameters"]["required_status_checks"] = [
        {"context": "web"}
    ]
    assert q.verify_main_rules(get, "t") is False


def test_empty_queue_is_real_and_not_a_merge_action():
    def get(token, path):
        if "rulesets?" in path:
            return []
        if "pulls?state=open" in path:
            return []
        raise AssertionError("unexpected API call: " + path)
    result = q.snapshot(get, "t")
    assert result["open_pr_count"] == 0
    assert result["rows"] == []
    assert result["can_merge"] is False
    assert result["rules_verified"] is False
    assert "No open PRs" in q.markdown(result)


def test_queue_requires_complete_pagination_and_nonpartial_file_diff():
    def too_many(token, path):
        return [sample_pr(number=i + 1) for i in range(100)]
    with pytest.raises(q.QueueHeld, match="PR_LIST_LIMIT_EXCEEDED"):
        q.load_open_prs(too_many, "t")

    def mismatched_files(token, path):
        if "rulesets?" in path: return []
        if "pulls?state=open" in path: return [sample_pr()]
        if path.endswith("/pulls/81"): return sample_pr()
        if path.endswith("/pulls/81/files?per_page=100"): return []
        raise AssertionError(path)
    with pytest.raises(q.QueueHeld, match="R22_PR_DIFF_INCOMPLETE"):
        q.snapshot(mismatched_files, "t")


def test_untrusted_titles_escape_summary_markup():
    row = q.evaluate(sample_pr(), nav_file(), {"state": "GREEN"}, True)
    row["title"] = "attack | <script>alert(1)</script>"
    data = {"captured_utc": "2026-10-31T00:00:00Z", "rules_verified": True,
            "open_pr_count": 1, "rows": [row]}
    rendered = q.markdown(data)
    assert "<script>" not in rendered
    assert r"\|" in rendered
    assert "merge_authorized" not in rendered


def test_api_client_does_not_accept_external_repo_paths():
    with pytest.raises(q.QueueHeld, match="R22_UNEXPECTED_API_PATH"):
        q.github_get("token", "/users/me")
