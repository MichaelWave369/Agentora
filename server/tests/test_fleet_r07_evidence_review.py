"""R0.7: GitHub provenance and ZIP-integrity review boundary tests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r06_pilot as pilot
import fleet_r07_evidence_review as review

SHA = "a" * 40
AGENTORA_HEAD = "b" * 40
RUN = 1234567
NOW = datetime(2026, 11, 3, 19, 0, tzinfo=timezone.utc)


class PilotGet:
    def __call__(self, path, token):
        if path.endswith("/branches/main"):
            return {"name": "main", "commit": {"sha": SHA}}
        return {"id": pilot.REPOSITORY_ID, "full_name": pilot.REPOSITORY,
                "owner": {"login": pilot.OWNER}, "private": False,
                "archived": False, "default_branch": "main"}


def make_files():
    preflight = pilot.prepare_pilot(
        SHA, pilot.CONFIRMATION, get=PilotGet(), clock=lambda: NOW - timedelta(minutes=12))
    steps = {"checkout_sha": SHA, "install_exit": 0, "test_exit": 0, "build_exit": 0}
    final = pilot.finalize_pilot(
        SHA, preflight, steps, get=PilotGet(), clock=lambda: NOW - timedelta(minutes=4),
        workflow_run_id=str(RUN))
    return {"preflight.json": preflight, "steps.json": steps, "final.json": final}


def pack(files=None, *, prefix="", extras=None):
    files = make_files() if files is None else files
    dest = io.BytesIO()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(prefix + path, json.dumps(content, sort_keys=True))
        for path, content in extras or []:
            archive.writestr(path, content)
    return dest.getvalue()


class GitHub:
    def __init__(self, raw, **run_overrides):
        self.paths = []
        self.run = {
            "id": RUN, "event": "workflow_dispatch",
            "path": review.WORKFLOW_PATH,
            "status": "completed", "conclusion": "success",
            "run_attempt": 1, "head_sha": AGENTORA_HEAD,
            "created_at": (NOW - timedelta(minutes=15)).isoformat(),
            "repository": {"id": review.AGENTORA_ID, "full_name": review.AGENTORA},
            "head_repository": {"full_name": review.AGENTORA},
        }
        self.run.update(run_overrides)
        self.artifacts = {
            "total_count": 1,
            "artifacts": [{
                "id": 987, "name": review.ARTIFACT_PREFIX + str(RUN),
                "expired": False, "size_in_bytes": len(raw),
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "workflow_run": {"id": RUN},
            }]
        }

    def __call__(self, path, token):
        self.paths.append((path, token))
        if path == "/repos/MichaelWave369/Agentora/actions/runs/" + str(RUN):
            return self.run
        if path == "/repos/MichaelWave369/Agentora/actions/runs/" + str(RUN) + "/artifacts?per_page=100":
            return self.artifacts
        raise AssertionError("Unexpected GitHub path " + path)


class EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.zip_bytes = pack()
        self.github = GitHub(self.zip_bytes)

    def review(self, raw=None, gh=None):
        return review.review(RUN, raw if raw is not None else self.zip_bytes,
                             github_get=gh or self.github, token="not-in-report",
                             clock=lambda: NOW)

    def test_r10_marker_is_bound_to_exact_run_artifact_not_authority(self):
        files = make_files()
        req_id = "r10r5-" + "e" * 40
        files["dispatch.json"] = pilot.dispatch_trace(SHA, req_id, str(RUN))
        raw = pack(files)
        result = self.review(raw=raw, gh=GitHub(raw))
        self.assertEqual(result["dispatch_request_id"], req_id)
        self.assertTrue(result["dispatch_trace_present"])
        self.assertFalse(result["dispatch_origin_authenticated"])
        self.assertFalse(result["dispatch_authorized"])
        self.assertFalse(result["merge_authorized"])

    def test_r10_marker_mutation_or_conflicting_run_is_rejected(self):
        marker = pilot.dispatch_trace(SHA, "r10r5-" + "e" * 40, str(RUN))
        for change in (
            {"run_id": RUN + 1},
            {"pilot_source_sha": "c" * 40},
            {"request_id": "malicious/id"},
            {"merge_authorized": True},
            {"dispatch_authorized": True},
            {"verified_complete": True},
            {"schema": "not-trace"},
            {"other": "extra"},
        ):
            with self.subTest(change=change):
                files = make_files()
                files["dispatch.json"] = {**marker, **change}
                raw = pack(files)
                with self.assertRaisesRegex(
                        review.ReviewHeld, "DISPATCH_TRACE_NOT_BOUND"):
                    self.review(raw=raw, gh=GitHub(raw))

    def test_matching_github_zip_produces_provenance_only(self):
        result = self.review()
        self.assertEqual(result["state"], "GITHUB_PILOT_ARTIFACT_DIGEST_CORRELATED")
        self.assertEqual(result["pilot_source_sha"], SHA)
        self.assertEqual(result["github_workflow_run"]["agentora_head_sha"], AGENTORA_HEAD)
        self.assertEqual(result["artifact"]["id"], 987)
        self.assertTrue(result["artifact"]["github_digest_matched"])
        self.assertEqual(result["observed_fixed_checks"]["vite_build"],
                         "EXIT_0_REPORTED_BY_PILOT")
        for field in ("signed_attestation", "independent_reproduction_performed",
                      "current_pilot_head_rechecked", "runtime_browser_verified",
                      "product_verified", "verified_complete", "merge_authorized",
                      "dispatch_authorized"):
            self.assertFalse(result[field])
        self.assertTrue(result["operator_review_required"])
        self.assertNotIn("not-in-report", json.dumps(result))
        self.assertEqual(len(self.github.paths), 2)

    def test_nested_pilot_control_zip_is_supported(self):
        raw = pack(prefix="pilot-control/")
        out = self.review(raw, GitHub(raw))
        self.assertEqual(out["pilot_source_sha"], SHA)

    def test_zip_modified_after_github_upload_is_rejected(self):
        mutated = bytearray(self.zip_bytes)
        mutated[-5] ^= 1
        with self.assertRaisesRegex(review.ReviewHeld, "ARTIFACT_DIGEST_MISMATCH"):
            self.review(bytes(mutated))

    def test_no_digest_or_unsafe_digest_refuses_proof(self):
        for value in (None, "", "sha1:" + "a" * 40, "sha256:" + "e" * 64):
            with self.subTest(value=value):
                g = GitHub(self.zip_bytes)
                g.artifacts["artifacts"][0]["digest"] = value
                with self.assertRaises(review.ReviewHeld):
                    self.review(gh=g)

    def test_wrong_run_event_status_path_attempt_or_repo_held(self):
        cases = [
            {"event": "pull_request"}, {"status": "in_progress"},
            {"conclusion": "failure"}, {"path": ".github/workflows/other.yml"},
            {"run_attempt": 2}, {"head_sha": "main"},
            {"repository": {"id": 99, "full_name": review.AGENTORA}},
            {"head_repository": {"full_name": "malicious/Agentora"}},
            {"id": RUN + 1}
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(review.ReviewHeld):
                    self.review(gh=GitHub(self.zip_bytes, **case))

    def test_missing_expired_ambiguous_or_wrong_run_artifact_held(self):
        for transform in (
            lambda g: g.artifacts.update(total_count=0, artifacts=[]),
            lambda g: g.artifacts["artifacts"][0].update(expired=True),
            lambda g: g.artifacts["artifacts"][0].update(workflow_run={"id": 3}),
            lambda g: g.artifacts.update(total_count=2, artifacts=[
                g.artifacts["artifacts"][0], deepcopy(g.artifacts["artifacts"][0])]),
            lambda g: g.artifacts["artifacts"][0].update(name="other-artifact"),
        ):
            gh = GitHub(self.zip_bytes)
            transform(gh)
            with self.assertRaises(review.ReviewHeld):
                self.review(gh=gh)

    def test_forged_zero_exit_code_claim_in_zip_not_trusted_without_digest(self):
        files = make_files()
        files["steps.json"]["test_exit"] = 1
        forged = pack(files)
        with self.assertRaisesRegex(review.ReviewHeld, "ARTIFACT_DIGEST_MISMATCH"):
            self.review(forged)

    def test_zip_traversal_or_unexpected_file_rejected(self):
        for extras in ([("../final.json", "oops")], [("private.key", "oops")],
                       [("pilot-control/foo.json", "{}")]):
            with self.subTest(extras=extras):
                raw = pack(extras=extras)
                with self.assertRaisesRegex(review.ReviewHeld,
                                            "UNEXPECTED_OR_DUPLICATE_ENTRY"):
                    self.review(raw, GitHub(raw))

    def test_duplicate_or_missing_required_member_rejected(self):
        original = make_files()
        no_final = dict(original)
        del no_final["final.json"]
        raw = pack(no_final)
        with self.assertRaisesRegex(review.ReviewHeld, "INCOMPLETE_PILOT_ARTIFACT"):
            self.review(raw, GitHub(raw))
        raw = pack(extras=[("final.json", "{}")])
        with self.assertRaisesRegex(review.ReviewHeld, "UNEXPECTED_OR_DUPLICATE_ENTRY"):
            self.review(raw, GitHub(raw))

    def test_forged_final_approval_or_product_done_flags_rejected(self):
        for flag in ("merge_authorized", "verified_complete", "product_verified",
                     "receipt_is_cryptographically_signed"):
            files = make_files()
            files["final.json"][flag] = True
            raw = pack(files)
            with self.subTest(flag=flag), self.assertRaisesRegex(
                review.ReviewHeld, "UNTRUSTED_AUTHORITY_CLAIM"):
                self.review(raw, GitHub(raw))

    def test_preflight_or_final_sha_conflict_rejected(self):
        variants = [
            ("preflight.json", "requested_sha", "c" * 40),
            ("preflight.json", "head_match", False),
            ("final.json", "source_sha", "c" * 40),
            ("final.json", "checkout_sha", "c" * 40),
        ]
        for file_name, field, replacement in variants:
            files = make_files()
            files[file_name][field] = replacement
            raw = pack(files)
            with self.subTest(field=field), self.assertRaises(review.ReviewHeld):
                self.review(raw, GitHub(raw))

    def test_failed_or_missing_checks_cannot_be_reported_green(self):
        variants = [
            ("steps.json", "test_exit", 1),
            ("steps.json", "build_exit", None),
            ("final.json", "automated_checks_passed", False),
            ("final.json", "state", "FAILED_NODE_TESTS"),
            ("final.json", "manual_checks", "PASSED"),
        ]
        for file_name, field, value in variants:
            files = make_files()
            files[file_name][field] = value
            raw = pack(files)
            with self.subTest(field=field), self.assertRaises(review.ReviewHeld):
                self.review(raw, GitHub(raw))

    def test_signed_or_empty_zip_refused(self):
        for payload in (b"", b"not-a-zip", b"\x50\x4b\x03\x04"):
            with self.subTest(payload=payload):
                with self.assertRaises(review.ReviewHeld):
                    self.review(payload, GitHub(payload))

    def test_missing_or_old_run_timestamp_fails(self):
        for val in ("yesterday", (NOW - timedelta(days=10)).isoformat()):
            with self.subTest(val=val):
                with self.assertRaises(review.ReviewHeld):
                    self.review(gh=GitHub(self.zip_bytes, created_at=val))

    def test_no_random_github_api_paths(self):
        for path in ("/user/repos",
                     "/repos/MichaelWave369/BTM/actions/runs/12",
                     "/repos/MichaelWave369/Agentora/actions/runs/12/jobs",
                     "/repos/MichaelWave369/Agentora/actions/runs/12?token=x"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(review.ReviewHeld, "UNSAFE_GITHUB_ENDPOINT"):
                    review.fixed_github_get(path)

    def test_invalid_run_id_is_rejected_before_network(self):
        for run_id in (-1, True, "1234", 10**20):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(review.ReviewHeld, "RUN_ID_INVALID"):
                    review.review(run_id, self.zip_bytes, github_get=self.github,
                                  clock=lambda: NOW)
        self.assertEqual(self.github.paths, [])


if __name__ == "__main__":
    unittest.main()
