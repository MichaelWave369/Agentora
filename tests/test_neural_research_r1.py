"""Adversarial tests for the Agentora proposal-only PhiStream research handoff."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "neural_research_r1.py"
spec = importlib.util.spec_from_file_location("neural_research_r1", SCRIPT)
lab = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lab
spec.loader.exec_module(lab)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


class NeuralResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        dataset = ("Experimental synthetic language data. The spark returns to source. " * 15).encode()
        trainer = b"# frozen trainer source, test fixture\n"
        self.config = dict(context=16, dim=32, heads=2, layers=1,
                           batch=4, steps=12, lr=0.003, seconds=120.0,
                           vram_mb=10240.0, seed=369, device="cpu",
                           study_id="test-neural", run_id="baseline")
        self.plan = dict(schema="PHI_NEURAL_PLAN_R1", study_id="test-neural",
                         run_id="baseline", engine="phi_tiny", metric="val_bpb",
                         direction="min", dataset_sha256=sha(dataset),
                         evaluator_sha256="a"*64, tokenizer_sha256="b"*64,
                         hardware_id="cpu-abc123", training_budget_seconds=120.0,
                         max_peak_vram_mb=10240.0,
                         source_ref="PhiStream:phistream/neural_tiny.py")
        self.log = ("val_bpb: 8.160050345\ntraining_seconds: 5.000000\n"
                    "total_seconds: 6.000000\npeak_vram_mb: 0.000000\n"
                    "num_steps: 12\nnum_params_M: 0.040000\n").encode()
        self.meta = dict(schema="PHI_TINY_TRAIN_R1", status="LOCAL_TRAINING_COMPLETED_UNVERIFIED",
                         config=self.config, plan=self.plan, steps=12,
                         final_val_bpb=8.160050345, train_code_sha256=sha(trainer),
                         production_authorized=False, quality_improvement_proven=False,
                         training_proven_authentic=False, checkpoint_saved=False,
                         network_used=False)
        self.receipt = self._receipt(self.plan, self.log, trainer)
        self.paths = {}
        for name, value in (("meta", self.meta), ("receipt", self.receipt)):
            self.paths[name] = self.root / (name + ".json")
            self.paths[name].write_text(json.dumps(value))
        for name, value in (("data", dataset), ("log", self.log), ("code", trainer)):
            self.paths[name] = self.root / (name + ".txt")
            self.paths[name].write_bytes(value)

    def _receipt(self, plan, log, code):
        metrics = lab.parse_log(log)
        result = dict(schema="PHI_NEURAL_LAB_R1", plan=dict(plan), metrics=metrics,
                      log_sha256=sha(log), code_sha256=sha(code), admissible=True,
                      reasons=[], assurance="self_declared_context_and_byte_integrity_only",
                      promotion="human_review_required")
        result["receipt_sha256"] = lab.digest(result)
        return result

    def baseline(self):
        return lab.inspect_baseline(self.meta, self.receipt,
                                    self.paths["data"].read_bytes(),
                                    self.paths["log"].read_bytes(),
                                    self.paths["code"].read_bytes())

    def test_baseline_matches(self):
        self.assertEqual(self.baseline()["metrics"]["num_steps"], 12)

    def test_readonly_preflight_cli(self):
        args = [sys.executable, str(SCRIPT), "preflight"]
        for k, v in self.paths.items():
            args += ["--" + k, str(v)]
        p = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse(json.loads(p.stdout)["execution_authorized"])
        self.assertEqual(sorted(x.name for x in self.root.iterdir()),
                         sorted(x.name for x in self.paths.values()))

    def test_proposal_reproducible_and_readonly(self):
        base = self.baseline()
        p = lab.propose(base, "lr", "0.0025")
        self.assertEqual(p, lab.propose(base, "lr", "0.0025"))
        self.assertEqual(p["candidate"]["run_id"], "trial-" + p["candidate"]["run_id"].split("-")[-1])
        self.assertEqual(p["candidate"]["steps"], 12)
        self.assertFalse(p["limits"]["execution_authorized"])
        self.assertEqual(p["comparison_contract"]["evaluator_sha256"], "a" * 64)
        self.assertEqual(lab.verify_proposal(p, base)["status"], "MATCHES_DECLARED_BASELINE")

    def test_parameter_change_rejected_if_same(self):
        with self.assertRaises(lab.ResearchHeld):
            lab.propose(self.baseline(), "lr", "0.003")

    def test_parameter_unknown_rejected(self):
        with self.assertRaises(lab.ResearchHeld):
            lab.propose(self.baseline(), "dataset_sha256", "5")

    def test_out_of_bounds_rejected(self):
        for name, value in (("lr", "0"), ("batch", "99"), ("layers", "0"), ("dim", "1024")):
            with self.subTest(name=name), self.assertRaises(lab.ResearchHeld):
                lab.propose(self.baseline(), name, value)

    def test_attn_divisibility_checked(self):
        with self.assertRaises(lab.ResearchHeld):
            lab.propose(self.baseline(), "heads", "3")

    def test_integer_must_be_canonical(self):
        with self.assertRaises(lab.ResearchHeld):
            lab.propose(self.baseline(), "batch", "2.0")

    def test_reject_tampered_receipt(self):
        self.receipt["metrics"]["val_bpb"] = 0.001
        with self.assertRaisesRegex(lab.ResearchHeld, "RECEIPT_CHANGED"):
            self.baseline()

    def test_reject_changed_source(self):
        self.paths["code"].write_bytes(b"# a changed trainer\n")
        with self.assertRaisesRegex(lab.ResearchHeld, "TRAINER_CODE_CHANGED"):
            self.baseline()

    def test_reject_changed_dataset(self):
        self.paths["data"].write_bytes(self.paths["data"].read_bytes() + b"x")
        with self.assertRaisesRegex(lab.ResearchHeld, "DATASET_MISMATCH"):
            self.baseline()

    def test_reject_changed_evaluator(self):
        self.meta["plan"]["evaluator_sha256"] = "f" * 64
        with self.assertRaisesRegex(lab.ResearchHeld, "BASELINE_PLAN_NOT_BOUND"):
            self.baseline()

    def test_reject_rejected_receipt(self):
        self.receipt["admissible"] = False
        self.receipt["reasons"] = ["vram_cap_exceeded"]
        self.receipt["receipt_sha256"] = lab.digest({k: v for k,v in self.receipt.items() if k != "receipt_sha256"})
        with self.assertRaisesRegex(lab.ResearchHeld, "RECEIPT_NOT_ADMISSIBLE"):
            self.baseline()

    def test_reject_changed_step_count(self):
        self.meta["steps"] = 7
        with self.assertRaisesRegex(lab.ResearchHeld, "META_METRIC_MISMATCH"):
            self.baseline()

    def test_reject_changed_log(self):
        self.paths["log"].write_bytes(self.log.replace(b"8.160050345", b"7.000000000"))
        with self.assertRaisesRegex(lab.ResearchHeld, "METRIC_LOG_CHANGED"):
            self.baseline()

    def test_reject_tampered_proposal(self):
        proposal = lab.propose(self.baseline(), "dim", "64")
        proposal["candidate"]["steps"] = 1
        with self.assertRaisesRegex(lab.ResearchHeld, "PROPOSAL_CHANGED"):
            lab.verify_proposal(proposal, self.baseline())

    def test_candidate_context_must_match(self):
        base = self.baseline()
        proposal = lab.propose(base, "batch", "8")
        new_plan = dict(self.plan, run_id=proposal["candidate"]["run_id"], evaluator_sha256="f"*64)
        candidate = self._receipt(new_plan, self.log, self.paths["code"].read_bytes())
        with self.assertRaisesRegex(lab.ResearchHeld, "CANDIDATE_EVALUATION_CONTEXT_CHANGED"):
            lab.assess(base, proposal, candidate)

    def test_candidate_steps_must_match(self):
        base = self.baseline()
        proposal = lab.propose(base, "lr", "0.002")
        candidate = self._receipt(dict(self.plan, run_id=proposal["candidate"]["run_id"]),
                                  self.log.replace(b"num_steps: 12", b"num_steps: 20"),
                                  self.paths["code"].read_bytes())
        with self.assertRaisesRegex(lab.ResearchHeld, "CANDIDATE_TRAINING_STEPS_CHANGED"):
            lab.assess(base, proposal, candidate)

    def test_candidate_trainer_digest_must_match(self):
        base = self.baseline()
        proposal = lab.propose(base, "lr", "0.002")
        candidate = self._receipt(dict(self.plan, run_id=proposal["candidate"]["run_id"]),
                                  self.log, b"# changed source\n")
        with self.assertRaisesRegex(lab.ResearchHeld, "CANDIDATE_TRAINER_CODE_CHANGED"):
            lab.assess(base, proposal, candidate)

    def test_review_does_not_promote(self):
        base = self.baseline()
        proposal = lab.propose(base, "lr", "0.002")
        candidate_log = self.log.replace(b"8.160050345", b"8.145000000")
        candidate = self._receipt(dict(self.plan, run_id=proposal["candidate"]["run_id"]),
                                  candidate_log, self.paths["code"].read_bytes())
        decision = lab.assess(base, proposal, candidate)
        self.assertEqual(decision["state"], "CANDIDATE_FOR_INDEPENDENT_REVIEW")
        self.assertFalse(decision["candidate_evidence_files_reverified"])
        self.assertFalse(decision["model_promotion_authorized"])
        self.assertFalse(decision["merge_authorized"])

    def test_new_file_exclusive(self):
        path = self.root / "proposal.json"
        lab.write_new(path, lab.propose(self.baseline(), "lr", "0.001"))
        with self.assertRaisesRegex(lab.ResearchHeld, "OUTPUT_MUST_BE_NEW"):
            lab.write_new(path, {"unexpected": True})

    def test_symlink_source_rejected(self):
        link = self.root / "data-link"
        try:
            link.symlink_to(self.paths["data"])
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks not supported on this host")
        with self.assertRaisesRegex(lab.ResearchHeld, "SOURCE_NOT_REGULAR_FILE"):
            lab.bounded_file(link)


if __name__ == "__main__":
    unittest.main()