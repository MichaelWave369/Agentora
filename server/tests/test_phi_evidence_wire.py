"""Adversarial deterministic regression coverage for the Phi evidence wire."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phi_evidence_wire.py"
spec = importlib.util.spec_from_file_location("phi_evidence_wire", SCRIPT)
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)

REPO = "MichaelWave369/PhiStream"
SHA = "a" * 40
DIGEST = "b" * 64


def gmed():
    return {
        "schema": "gmed-report:v1", "state": "GMED",
        "merged": True, "sha": SHA,
        "counts": {"total": 2, "passed": 1, "accepted": 2,
                   "failed": 0, "pending": 0, "unknown": 0},
        "checks": [
            {"kind": "check", "name": "ci", "status": "completed",
             "conclusion": "success", "grade": "good"},
            {"kind": "check", "name": "optional", "status": "completed",
             "conclusion": "skipped", "grade": "good"},
        ],
    }


def r14():
    return {
        "schema": "agentora.fleet.r14.evidence-handoff.v1",
        "target_repository": REPO, "source_sha": SHA,
        "state": "EVIDENCE_LINKED_PENDING_OWNER_REVIEW", "command": "link",
        "owner_acknowledged": False,
        "mission_issue": 132, "audit_run_id": 321, "qa_run_id": 322,
        "issue_sha256": DIGEST, "audit_artifact_sha256": DIGEST,
        "qa_artifact_sha256": DIGEST,
        "code_write_blocked": True, "worker_execution_authorized": False,
        "independent_human_qa_complete": False,
        "merge_authorized": False, "deployment_authorized": False,
    }


def clavis():
    return {
        "schema": "phistream.clavis.qualification-review.v0.3",
        "status": "SCREENED_FOR_FURTHER_INDEPENDENT_REVIEW_ONLY",
        "quality_proven": False, "routing_activated": False,
        "deployment_authorized": False,
        "private_prompts_answers_or_mappings_exported": False,
    }


class EvidenceWireTests(unittest.TestCase):
    def assert_held(self, g=None, r=None, c=None, repo=REPO, sha=SHA):
        with self.assertRaises(wire.EvidenceHeld):
            wire.correlate(repo, sha, g if g is not None else gmed(),
                           r if r is not None else r14(), c)

    def test_two_existing_contracts_correlate_without_authority(self):
        result = wire.correlate(REPO, SHA, gmed(), r14())
        self.assertEqual(result["state"], "CORRELATED_REVIEW_ONLY")
        self.assertEqual(set(result["evidence"]), {"gmed", "agentora_r14"})
        self.assertEqual(result["source_sha"], SHA)
        for key in ("source_authentication_independent", "formal_proof_checked",
                    "model_routing_activated", "code_write_authorized",
                    "worker_dispatch_authorized", "merge_authorized",
                    "deployment_authorized"):
            self.assertIs(result[key], False)

    def test_cross_repo_clavis_is_research_only(self):
        result = wire.correlate(REPO, SHA, gmed(), r14(), clavis())
        self.assertEqual(result["evidence"]["phistream_clavis"]["status"],
                         "RESEARCH_SUMMARY_NOT_SOURCE_BOUND")
        self.assertIs(result["formal_proof_checked"], False)

    def test_gmed_wrong_source_sha(self):
        bad = gmed()
        bad["sha"] = "c" * 40
        self.assert_held(g=bad)

    def test_gmed_not_merged(self):
        bad = gmed()
        bad["merged"] = False
        self.assert_held(g=bad)

    def test_gmed_misreported_arithmetic(self):
        bad = gmed()
        bad["counts"]["passed"] = 2
        self.assert_held(g=bad)

    def test_gmed_zero_real_success(self):
        bad = gmed()
        bad["checks"][0]["conclusion"] = "neutral"
        bad["counts"]["passed"] = 0
        self.assert_held(g=bad)

    def test_gmed_failed_check_disguised_as_good(self):
        bad = gmed()
        bad["checks"][0]["conclusion"] = "failure"
        self.assert_held(g=bad)

    def test_r14_wrong_repo(self):
        bad = r14()
        bad["target_repository"] = "MichaelWave369/PhiOS"
        self.assert_held(r=bad)

    def test_r14_wrong_sha(self):
        bad = r14()
        bad["source_sha"] = "c" * 40
        self.assert_held(r=bad)

    def test_r14_malformed_state_holds(self):
        bad = r14()
        bad["state"] = []
        self.assert_held(r=bad)

    def test_r14_fake_owner_ack(self):
        bad = r14()
        bad["owner_acknowledged"] = True
        self.assert_held(r=bad)

    def test_r14_no_merge_escalation(self):
        bad = r14()
        bad["merge_authorized"] = True
        self.assert_held(r=bad)

    def test_r14_no_dispatch_escalation(self):
        bad = r14()
        bad["worker_execution_authorized"] = True
        self.assert_held(r=bad)

    def test_r14_separate_owner_ack_is_still_not_approval(self):
        item = r14()
        item["state"] = "OWNER_REVIEW_ACKNOWLEDGED_NO_APPROVAL"
        item["command"] = "acknowledge"
        item["owner_acknowledged"] = True
        report = wire.correlate(REPO, SHA, gmed(), item)
        self.assertIs(report["merge_authorized"], False)

    def test_clavis_cannot_escalate_to_prod(self):
        bad = clavis()
        bad["deployment_authorized"] = True
        self.assert_held(c=bad)

    def test_clavis_refuses_private_payload(self):
        bad = clavis()
        bad["private_answer_key"] = {"mapping": "secret"}
        self.assert_held(c=bad)

    def test_unpinned_sha_and_bad_repo(self):
        self.assert_held(sha="main")
        self.assert_held(repo="../etc")

    def test_input_rejects_symlink_and_excessive_file_size(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            original = base / "gmed.json"
            original.write_text(json.dumps(gmed()), encoding="utf-8")
            self.assertEqual(wire.load_public_summary(original)["state"], "GMED")
            oversize = base / "huge.json"
            oversize.write_text("x" * (wire.MAX_INPUT_BYTES + 1))
            with self.assertRaises(wire.EvidenceHeld):
                wire.load_public_summary(oversize)
            link = base / "alias.json"
            try:
                link.symlink_to(original)
            except OSError:
                return
            with self.assertRaises(wire.EvidenceHeld):
                wire.load_public_summary(link)


if __name__ == "__main__":
    unittest.main()
