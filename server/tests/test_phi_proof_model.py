"""Synthetic negative cases for the Lean proof receipt, no Lean installation needed."""
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2] / "scripts/phi_proof_model.py"
spec = importlib.util.spec_from_file_location("phi_proof_model", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SHA = "a" * 40


class FakeRunner:
    def __init__(self, *, sha=SHA, version="Lean (version 4.35.0, x86_64)",
                 failed=None):
        self.sha = sha
        self.version = version
        self.failed = failed
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv == ["git", "rev-parse", "HEAD"]:
            stdout = self.sha + "\n"
        elif argv == ["lean", "--version"]:
            stdout = self.version + "\n"
        else:
            stdout = "Lean proof model checked.\n"
        code = 1 if argv == self.failed else 0
        return subprocess.CompletedProcess(argv, code, stdout, "")


class ProofModelTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        for item in mod.SOURCE_FILES:
            path = self.root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("valid code\n", encoding="utf-8")
        (self.root / "formal/phi-evidence/lean-toolchain").write_text(
            mod.TOOLCHAIN + "\n", encoding="utf-8")

    def test_kernel_receipt_has_no_privileges_or_runtime_claims(self):
        fake = FakeRunner()
        report = mod.build_receipt(self.root, SHA, runner=fake)
        self.assertEqual(report["state"], "LEAN_ABSTRACT_MODEL_CHECKED_REVIEW_ONLY")
        self.assertEqual(report["checked_commit_sha"], SHA)
        self.assertEqual(len(report["file_sha256"]), len(mod.SOURCE_FILES))
        self.assertTrue(report["proof_model_kernel_checked_in_this_process"])
        self.assertEqual(fake.calls[2], ["lake", "build", "--wfail"])
        self.assertEqual(fake.calls[3][:3], ["lake", "env", "lean"])
        for key in (
            "source_code_behavior_proven", "compiled_machine_code_proven",
            "github_metadata_independently_authenticated",
            "operator_policy_auto_approved", "model_routing_activated",
            "code_write_authorized", "worker_dispatch_authorized",
            "merge_authorized", "deployment_authorized",
        ):
            self.assertIs(report[key], False)

    def test_different_checkout_sha_is_a_hold(self):
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA,
                              runner=FakeRunner(sha="b" * 40))

    def test_missing_sha_is_a_hold_before_running_checker(self):
        fake = FakeRunner()
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, None, runner=fake)
        self.assertEqual(fake.calls, [])

    def test_toolchain_version_drift_is_a_hold(self):
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA,
                              runner=FakeRunner(version="Lean (version 4.99.0)"))

    def test_toolchain_file_drift_is_a_hold(self):
        (self.root / "formal/phi-evidence/lean-toolchain").write_text(
            "leanprover/lean4:stable\n", encoding="utf-8")
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA, runner=FakeRunner())

    def test_sorry_placeholder_is_not_accepted(self):
        file = self.root / "formal/phi-evidence/PhiEvidence.lean"
        file.write_text("theorem bogus : True := by sorry\n", encoding="utf-8")
        fake = FakeRunner()
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA, runner=fake)
        self.assertEqual(fake.calls, [])

    def test_axiom_introduction_is_not_accepted(self):
        file = self.root / "formal/phi-evidence/PhiEvidence.lean"
        file.write_text("axiom bogus : True\n", encoding="utf-8")
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA, runner=FakeRunner())

    def test_failed_build_never_emits_success(self):
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA,
                              runner=FakeRunner(failed=["lake", "build", "--wfail"]))

    def test_failed_kernel_never_emits_success(self):
        command = ["lake", "env", "lean", "-DwarningAsError=true",
                   "PhiEvidence.lean"]
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA,
                              runner=FakeRunner(failed=command))

    def test_missing_source_is_a_hold(self):
        (self.root / "scripts/phi_evidence_live.py").unlink()
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA, runner=FakeRunner())

    def test_source_digest_tracks_actual_bytes(self):
        a = mod.build_receipt(self.root, SHA, runner=FakeRunner())
        target = self.root / "scripts/phi_evidence_wire.py"
        target.write_text("changed code\n", encoding="utf-8")
        b = mod.build_receipt(self.root, SHA, runner=FakeRunner())
        self.assertNotEqual(a["file_sha256"]["scripts/phi_evidence_wire.py"],
                            b["file_sha256"]["scripts/phi_evidence_wire.py"])

    def test_symlink_source_is_rejected(self):
        source = self.root / "scripts/phi_evidence_live.py"
        alias = self.root / "scripts/alias.py"
        alias.write_text("data\n", encoding="utf-8")
        source.unlink()
        try:
            source.symlink_to(alias)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported here")
        with self.assertRaises(mod.ProofHeld):
            mod.build_receipt(self.root, SHA, runner=FakeRunner())


if __name__ == "__main__":
    unittest.main()
