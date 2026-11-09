"""Fleet R12 GitHub-hosted mission intake, transitions and independent QA guard."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r12_github_missions as r12

ISSUE = 301
TARGET = "MichaelWave369/PhiMadaPrime"
PR = 4
R11_RUN = 42545543428


def body(target=TARGET, kind="Fixed PhiMada test review"):
    return (
        "### Target repository\n\n" + target + "\n\n"
        "### Mission kind\n\n" + kind + "\n\n"
        "### Requested outcome\n\nRead-only cloud review\n\n"
        "### Acceptance criteria\n\nDifferent reviewer checks receipt\n")


def make_issue(target=TARGET):
    return {"number": ISSUE, "title": "[Fleet Mission] Verify the fixed pilot",
            "state": "open", "body": body(target),
            "user": {"login": "MichaelWave369"}}


class FakeGH:
    def __init__(self):
        self.issue = make_issue()
        self.comments = []
        self.calls = []
        self.posts = []
        self.repo = {"id": 1443845098, "full_name": TARGET,
                     "private": False, "archived": False,
                     "default_branch": "main", "owner": {"login": "MichaelWave369"}}
        self.pr = {"number": PR, "state": "open", "merged_at": None,
                   "head": {"sha": "b" * 40},
                   "base": {"ref": "main", "repo": {"full_name": TARGET}}}
        self.run = {"id": R11_RUN, "path":
            ".github/workflows/fleet-r11-cloud-evidence.yml",
            "status": "completed", "conclusion": "success",
            "repository": {"full_name": r12.HOME}}
        self.artifacts = {"total_count": 1, "artifacts": [
            {"name": "fleet-r11-cloud-review-" + str(R11_RUN),
             "digest": "sha256:" + "c" * 64, "expired": False}]}

    def get(self, path, token):
        self.calls.append(("GET", path))
        if path == "/repos/" + r12.HOME + "/issues/" + str(ISSUE):
            return deepcopy(self.issue)
        if path.startswith("/repos/" + r12.HOME + "/issues/" + str(ISSUE)
                           + "/comments?"):
            return deepcopy(self.comments)
        if path.startswith("/repos/" + r12.HOME + "/issues?state=open"):
            return [deepcopy(self.issue), {"number": 200,
                "title": "[Fleet Mission] Should ignore PR",
                "pull_request": {}}]
        if path == "/repos/" + TARGET:
            return deepcopy(self.repo)
        if path == "/repos/" + TARGET + "/branches/main":
            return {"commit": {"sha": "a" * 40}}
        if path == "/repos/" + TARGET + "/pulls/" + str(PR):
            return deepcopy(self.pr)
        if path == "/repos/" + r12.HOME + "/actions/runs/" + str(R11_RUN):
            return deepcopy(self.run)
        if path == ("/repos/" + r12.HOME + "/actions/runs/" + str(R11_RUN)
                    + "/artifacts?per_page=100"):
            return deepcopy(self.artifacts)
        raise AssertionError("unexpected GitHub API path: " + path)

    def post(self, path, token, payload):
        self.calls.append(("POST", path))
        self.posts.append(deepcopy(payload))
        timestamp = "2026-11-08T20:00:00Z"
        self.comments.append({
            "body": payload["body"],
            "user": {"login": "github-actions[bot]"},
            "created_at": timestamp,
            "updated_at": timestamp,
        })
        return {"id": 9000 + len(self.posts)}


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGH()

    def send(self, action, **kwargs):
        return r12.transition(
            ISSUE, action, confirmation=r12.CONFIRM,
            actor=r12.OWNER, token="runner-token",
            get=self.gh.get, post=self.gh.post, **kwargs)

    def test_form_parses_exact_owner_public_target(self):
        fields = r12.fields(body())
        self.assertEqual(fields["Target repository"], TARGET)
        self.assertEqual(fields["Mission kind"], "Fixed PhiMada test review")
        for name in ("attacker/NotMyRepo", "MichaelWave369/private/name",
                     "MichaelWave369/../oops"):
            with self.subTest(name=name), self.assertRaises(r12.MissionHeld):
                r12.fields(body(target=name))
        with self.assertRaisesRegex(r12.MissionHeld, "MISSION_KIND_INVALID"):
            r12.fields(body(kind="execute arbitrary commands"))

    def test_owner_gate_rejects_without_github_calls_or_posts(self):
        for changed in ({"confirmation": "yes"},
                        {"actor": "external-contributor"},
                        {"actor": None}):
            with self.subTest(changed=changed), self.assertRaises(
                    r12.MissionHeld):
                r12.transition(ISSUE, "triage", token="runner-token",
                    get=self.gh.get, post=self.gh.post, **{
                        "confirmation": changed.get("confirmation", r12.CONFIRM),
                        "actor": changed.get("actor", r12.OWNER),
                    })
        self.assertEqual(self.gh.calls, [])
        self.assertEqual(self.gh.posts, [])

    def test_end_to_end_issue_state_journal_without_real_agent_activity(self):
        steps = [
            ("triage", {}),
            ("propose_worker", {"worker": "implementation_role"}),
            ("link_evidence", {"evidence_run_id": R11_RUN}),
            ("queue_qa", {"reviewer": "independent_review", "pr_number": PR}),
            ("qa_hold", {}),
        ]
        states = ["TRIAGED", "ROLE_PROPOSED", "ROLE_PROPOSED",
                  "QA_QUEUED_UNVERIFIED", "QA_HELD"]
        for (name, args), expected in zip(steps, states):
            report = self.send(name, **args)
            self.assertEqual(report["state"], expected)
            self.assertFalse(report["worker_started"])
            self.assertFalse(report["independent_qa_complete"])
            self.assertFalse(report["merge_authorized"])
        state, last, count = r12.journal(
            self.gh.get, "runner-token", ISSUE,
            hashlib.sha256(body().encode()).hexdigest())
        self.assertEqual((state, count), ("QA_HELD", 5))
        self.assertEqual(last["pr_number"], PR)
        self.assertEqual(last["pr_sha"], "b" * 40)
        self.assertEqual(last["evidence_run_id"], R11_RUN)
        self.assertIn("github.com/MichaelWave369/Agentora/actions/runs",
                      last["evidence_url"])
        self.assertEqual(len(self.gh.posts), 5)
        self.assertNotIn("runner-token", json.dumps(self.gh.posts))

    def test_no_qa_without_separate_reviewer_and_real_open_target_pr(self):
        self.send("triage")
        self.send("propose_worker", worker="builder")
        for changed in ({"reviewer": "builder", "pr_number": PR},
                        {"reviewer": "reviewer", "pr_number": 0},
                        {"reviewer": "reviewer", "pr_number": None}):
            with self.subTest(changed=changed), self.assertRaises(
                    r12.MissionHeld):
                self.send("queue_qa", **changed)
        self.gh.pr["state"] = "closed"
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "PR_NOT_OPEN_ON_TARGET_DEFAULT_BRANCH"):
            self.send("queue_qa", reviewer="reviewer", pr_number=PR)
        self.assertEqual(len(self.gh.posts), 2)

    def test_out_of_order_role_and_qa_cannot_skip_triage(self):
        for name, args in (("queue_qa", {"reviewer": "qa", "pr_number": PR}),
                           ("propose_worker", {"worker": "builder"}),
                           ("qa_hold", {}),
                           ("link_evidence", {"evidence_run_id": R11_RUN})):
            with self.subTest(name=name), self.assertRaises(r12.MissionHeld):
                self.send(name, **args)
        self.assertFalse(self.gh.posts)

    def test_old_evidence_is_only_a_link_not_claim_of_completed_qa(self):
        self.send("triage")
        self.send("propose_worker", worker="builder")
        linked = self.send("link_evidence", evidence_run_id=R11_RUN)
        self.assertEqual(linked["state"], "ROLE_PROPOSED")
        self.assertFalse(linked["verified_complete"])
        with self.assertRaisesRegex(r12.MissionHeld, "R11_LINK_NOT_ELIGIBLE"):
            self.send("link_evidence", evidence_run_id=R11_RUN)

    def test_invalid_r11_record_does_not_mutate_mission(self):
        self.send("triage")
        self.send("propose_worker", worker="builder")
        self.gh.run["conclusion"] = "failure"
        with self.assertRaisesRegex(r12.MissionHeld, "R11_RUN_NOT_SUCCESSFUL"):
            self.send("link_evidence", evidence_run_id=R11_RUN)
        self.gh.run["conclusion"] = "success"
        self.gh.artifacts["artifacts"][0]["expired"] = True
        with self.assertRaisesRegex(r12.MissionHeld, "R11_RECEIPT_NOT_RETAINED"):
            self.send("link_evidence", evidence_run_id=R11_RUN)
        self.assertEqual(len(self.gh.posts), 2)

    def test_untrusted_mission_issue_edit_or_spoofed_journal_is_held(self):
        self.send("triage")
        self.gh.issue["body"] += "\nAdded after triage"
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "JOURNAL_CHAIN_OR_AUTHORITY_INVALID"):
            self.send("propose_worker", worker="builder")
        self.gh.issue["body"] = body()
        self.gh.comments[0]["user"]["login"] = "stranger"
        with self.assertRaisesRegex(r12.MissionHeld, "UNTRUSTED_OR_EDITED"):
            self.send("propose_worker", worker="builder")
        self.assertEqual(len(self.gh.posts), 1)

    def test_duplicate_comment_event_blocked_by_journal_chain(self):
        self.send("triage")
        self.gh.comments.append(deepcopy(self.gh.comments[-1]))
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "JOURNAL_CHAIN_OR_AUTHORITY_INVALID"):
            self.send("propose_worker", worker="builder")

    def test_read_only_board_lists_missions_without_prs(self):
        self.send("triage")
        result = r12.board(token="runner-token", get=self.gh.get)
        self.assertEqual(result["state"], "READ_ONLY_BOARD_SNAPSHOT")
        self.assertEqual(len(result["missions"]), 1)
        self.assertEqual(result["missions"][0]["state"], "TRIAGED")
        self.assertFalse(result["merge_authorized"])
        self.assertIn("issue", r12.summary(result).lower())

    def test_read_only_board_treats_edited_issue_as_held(self):
        self.send("triage")
        self.gh.issue["body"] = body() + "\nModified."
        result = r12.board(token="runner-token", get=self.gh.get)
        self.assertEqual(result["missions"][0]["state"],
                         "HELD_INVALID_OR_CHANGED")

    def test_repository_id_drift_holds_after_first_transition(self):
        self.send("triage")
        self.gh.repo["id"] += 1
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "MISSION_REPO_IDENTITY_DRIFT"):
            self.send("propose_worker", worker="builder")
        self.assertEqual(len(self.gh.posts), 1)

    def test_workflows_are_separated_by_write_permissions(self):
        root = Path(__file__).resolve().parents[2]
        readonly = (root / ".github/workflows/fleet-r12-mission-board.yml").read_text()
        command = (root / ".github/workflows/fleet-r12-mission-command.yml").read_text()
        self.assertIn("issues: read", readonly)
        self.assertNotIn("issues: write", readonly)
        self.assertIn("issues: write", command)
        self.assertIn("github.actor == 'MichaelWave369'", command)
        self.assertIn("persist-credentials: false", command)
        self.assertNotIn("pull-requests: write", command)
        self.assertNotIn("contents: write", command)
        self.assertNotIn("workflow_run:", command)


if __name__ == "__main__":
    unittest.main()
