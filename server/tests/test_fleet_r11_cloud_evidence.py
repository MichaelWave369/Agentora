"""Zero-install R11: hosted, read-only GitHub pilot evidence validation."""
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
sys.path.insert(0, str(HERE.parent))
import fleet_r11_cloud_evidence as cloud
import fleet_r07_evidence_review as r07
import fleet_r06_pilot as pilot
import test_fleet_r07_evidence_review as fixture

RUN = fixture.RUN
SHA = fixture.SHA
NOW = fixture.NOW


class HostedReviewTests(unittest.TestCase):
    def _review(self, raw=None, github=None):
        raw = fixture.pack() if raw is None else raw
        github = fixture.GitHub(raw) if github is None else github
        ids = []

        def fetch(artifact_id, token):
            ids.append((artifact_id, token))
            return raw

        result = cloud.review_run(
            RUN, token="read-only-token", get=github, download=fetch,
            clock=lambda: NOW)
        return result, ids, github

    def test_historical_artifact_validated_without_claiming_new_mission(self):
        report, ids, github = self._review()
        self.assertEqual(report["state"],
                         "GITHUB_FIXED_PILOT_EVIDENCE_CORRELATED")
        self.assertEqual(report["pilot_source_sha"], SHA)
        self.assertEqual(report["github_artifact_sha256"],
                         hashlib.sha256(fixture.pack()).hexdigest())
        self.assertTrue(report["historical_untraced_run"])
        self.assertFalse(report["dispatch_trace_present"])
        self.assertIsNone(report["dispatch_request_id"])
        self.assertEqual(ids, [(987, "read-only-token")])
        self.assertEqual(len(github.paths), 4)
        for name in ("independent_qa_performed", "product_verified",
                     "verified_complete", "merge_authorized",
                     "dispatch_origin_authenticated",
                     "dispatch_authorized"):
            self.assertFalse(report[name])
        self.assertNotIn("read-only-token", json.dumps(report))

    def test_new_traced_artifact_records_public_request_not_authorization(self):
        files = fixture.make_files()
        request_id = "r10r5-" + "d" * 40
        files["dispatch.json"] = pilot.dispatch_trace(SHA, request_id, str(RUN))
        raw = fixture.pack(files)
        report, ids, github = self._review(raw)
        self.assertEqual(report["dispatch_request_id"], request_id)
        self.assertTrue(report["dispatch_trace_present"])
        self.assertFalse(report["historical_untraced_run"])
        self.assertFalse(report["dispatch_origin_authenticated"])
        self.assertFalse(report["merge_authorized"])

    def test_tampered_zip_refuses_verification(self):
        raw = bytearray(fixture.pack())
        raw[-6] ^= 1
        with self.assertRaisesRegex(r07.ReviewHeld,
                                    "ARTIFACT_DIGEST_MISMATCH"):
            self._review(bytes(raw), fixture.GitHub(fixture.pack()))

    def test_untrusted_run_refused_before_download(self):
        raw = fixture.pack()
        for alter in ({"path": ".github/workflows/other.yml"},
                      {"event": "push"},
                      {"conclusion": "failure"},
                      {"run_attempt": 2},
                      {"head_sha": "bad"}):
            with self.subTest(alter=alter):
                github = fixture.GitHub(raw, **alter)
                called = []
                with self.assertRaises(cloud.CloudReviewHeld):
                    cloud.review_run(
                        RUN, token="token", get=github,
                        download=lambda *_args: called.append("called"),
                        clock=lambda: NOW)
                self.assertEqual(called, [])

    def test_missing_duplicate_expired_and_wrong_artifact_metadata_hold(self):
        original = fixture.pack()
        for mutate in (
            lambda g: g.artifacts.update(artifacts=[], total_count=0),
            lambda g: g.artifacts["artifacts"][0].update(expired=True),
            lambda g: g.artifacts["artifacts"][0].update(id=True),
            lambda g: g.artifacts["artifacts"][0].update(digest="bad"),
            lambda g: g.artifacts.update(
                artifacts=[*g.artifacts["artifacts"], *g.artifacts["artifacts"]],
                total_count=2),
        ):
            gh = fixture.GitHub(original)
            mutate(gh)
            with self.subTest(artifacts=gh.artifacts):
                with self.assertRaises(cloud.CloudReviewHeld):
                    cloud.review_run(
                        RUN, token="read", get=gh,
                        download=lambda *_args: original, clock=lambda: NOW)

    def test_forged_trace_flags_rejected_by_existing_r07(self):
        files = fixture.make_files()
        files["dispatch.json"] = {
            **pilot.dispatch_trace(SHA, "r10r5-" + "e" * 40, str(RUN)),
            "merge_authorized": True,
        }
        raw = fixture.pack(files)
        with self.assertRaisesRegex(r07.ReviewHeld,
                                    "DISPATCH_TRACE_NOT_BOUND"):
            self._review(raw)

    def test_invalid_or_old_run_ids_hold(self):
        raw = fixture.pack()
        for run_id in (True, 0, -1, 2**70, "123"):
            with self.subTest(run_id=run_id):
                with self.assertRaises(cloud.CloudReviewHeld):
                    cloud.review_run(run_id, token="read",
                        get=fixture.GitHub(raw), download=lambda *_: raw,
                        clock=lambda: NOW)
        with self.assertRaises(cloud.CloudReviewHeld):
            cloud.review_run(
                RUN, token="read", get=fixture.GitHub(raw),
                download=lambda *_: raw, clock=lambda: NOW + timedelta(days=9))

    def test_artifact_redirect_host_is_allowlisted(self):
        for url in (
            "https://evil.example/payload",
            "http://foo.blob.core.windows.net/blob",
            "https://blob.core.windows.net.evil.test/blob",
            "https://user:pass@storage.blob.core.windows.net/blob",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url):
                with self.assertRaises(cloud.CloudReviewHeld):
                    cloud._safe_blob(url)
        self.assertEqual(cloud._safe_blob(
            "https://storage.blob.core.windows.net/path?sig=123"),
            "https://storage.blob.core.windows.net/path?sig=123")

    def test_download_never_forwards_operator_token_to_storage_host(self):
        raw = fixture.pack()
        blob = "https://storage.blob.core.windows.net/archive?sig=public"
        calls = []

        class BlobResponse:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, amount):
                return raw

        class FakeOpener:
            def open(self, request, timeout):
                calls.append(request)
                if len(calls) == 1:
                    raise HTTPError(
                        request.full_url, 302, "Moved",
                        {"Location": blob}, None)
                return BlobResponse()

        with patch.object(cloud, "build_opener",
                          return_value=FakeOpener()):
            received = cloud.download_artifact(123, "secret-operator-token")
        self.assertEqual(received, raw)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].full_url,
                         "https://api.github.com/repos/MichaelWave369/"
                         "Agentora/actions/artifacts/123/zip")
        self.assertIn("secret-operator-token",
                      str(calls[0].headers.get("Authorization")))
        self.assertEqual(calls[1].full_url, blob)
        self.assertNotIn("Authorization", calls[1].headers)

    def test_run_summary_is_honest_and_no_user_input_code_execution(self):
        report, _, _ = self._review()
        summary = cloud._summary(report)
        self.assertIn("Independent QA: **not performed**", summary)
        self.assertIn("none (legacy untraced)", summary)
        self.assertIn("merge, and deployment: **not authorized**", summary)
        held = cloud._summary({"state": "HELD_NO_ARTIFACT"})
        self.assertIn("No verified success", held)

    def test_workflow_read_only_on_github_hosted_runner(self):
        yaml = (HERE.parents[2] / ".github" / "workflows" /
                "fleet-r11-cloud-evidence.yml").read_text()
        self.assertIn("workflow_run:", yaml)
        self.assertIn("workflow_dispatch:", yaml)
        self.assertIn("  contents: read", yaml)
        self.assertIn("  actions: read", yaml)
        self.assertNotIn("contents: write", yaml)
        self.assertNotIn("actions: write", yaml)
        self.assertNotIn("pull-requests: write", yaml)
        self.assertNotIn("python scripts/fleet_r5_guarded_dispatch.py", yaml)


if __name__ == "__main__":
    unittest.main()
