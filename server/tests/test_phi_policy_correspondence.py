"""R0.4: negative tests proving the correspondence harness catches mutations."""
import itertools
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devloop_r2_policy as policy
import phi_policy_correspondence as runner

SHA = "a" * 40


def synthetic_oracle():
    lines = []
    for inputs in itertools.product("01", repeat=4):
        bits = "".join(inputs)
        # Synthetic fixture only; real CI executes Lean separately.
        lines.append(f"G|{bits}|{int(bits == '1111')}")
    for level in runner.LEVELS:
        lines.append(f"E|{level}|0000")
    return "\n".join(lines) + "\n"


class FakeProcess:
    def __init__(self, *, sha=SHA, version="Lean (version 4.35.0, linux)",
                 oracle=None, failed=None):
        self.sha = sha
        self.version = version
        self.oracle = oracle if oracle is not None else synthetic_oracle()
        self.failed = failed
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd == ["git", "rev-parse", "HEAD"]:
            value = self.sha + "\n"
        elif cmd == ["lean", "--version"]:
            value = self.version + "\n"
        elif cmd == ["lake", "env", "lean", "--run", "PolicyOracle.lean"]:
            value = self.oracle
        else:
            raise AssertionError(f"unexpected command: {cmd}")
        return subprocess.CompletedProcess(cmd, 1 if cmd == self.failed else 0,
                                           value, "")


class CorrespondenceTests(unittest.TestCase):
    def test_all_48_synthetic_model_vectors_correspond(self):
        self.assertEqual(runner.compare(synthetic_oracle()), 48)

    def test_policy_is_read_only_even_all_gates_true(self):
        result = policy.correspondence_policy_snapshot(
            True, True, True, True, "formallyCheckedModel")
        self.assertTrue(result["model_gate_conjunction"])
        self.assertFalse(result["action_authorized"])
        self.assertEqual(set(result["evidence_authority"].values()), {False})

    def test_invalid_non_boolean_inputs_are_held(self):
        for bogus in (1, 0, "true", None, [], {}):
            with self.assertRaises(policy.CodeHeld):
                policy.correspondence_policy_snapshot(
                    bogus, True, True, True, "declared")

    def test_unknown_evidence_tier_is_held(self):
        for bad in ("PROVED", 9, None, ""):
            with self.assertRaises(policy.CodeHeld):
                policy.correspondence_policy_snapshot(
                    True, True, True, True, bad)

    def test_mutated_python_gate_is_detected(self):
        original = policy.correspondence_policy_snapshot
        def mutant(a, b, c, d, tier):
            result = original(a, b, c, d, tier)
            # Deliberate "logic above lies" red-team mutation.
            result["model_gate_conjunction"] = not result["model_gate_conjunction"]
            return result
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "DIVERGES"):
            runner.compare(synthetic_oracle(), implementation=mutant)

    def test_mutated_python_authority_is_detected(self):
        original = policy.correspondence_policy_snapshot
        def mutant(a, b, c, d, tier):
            result = original(a, b, c, d, tier)
            result["evidence_authority"]["merge"] = True
            return result
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "DIVERGES"):
            runner.compare(synthetic_oracle(), implementation=mutant)

    def test_mutated_action_authorization_is_detected(self):
        original = policy.correspondence_policy_snapshot
        def mutant(a, b, c, d, tier):
            result = original(a, b, c, d, tier)
            result["action_authorized"] = True
            return result
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "PRIVILEGE"):
            runner.compare(synthetic_oracle(), implementation=mutant)

    def test_mutated_python_schema_is_detected(self):
        original = policy.correspondence_policy_snapshot
        def mutant(a, b, c, d, tier):
            result = original(a, b, c, d, tier)
            del result["review_only"]
            return result
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "SHAPE"):
            runner.compare(synthetic_oracle(), implementation=mutant)

    def test_oracle_cannot_omit_one_vector(self):
        rows = synthetic_oracle().splitlines()
        with self.assertRaises(runner.CorrespondenceHeld):
            runner.parse_oracle("\n".join(rows[1:]) + "\n")

    def test_oracle_cannot_repeat_one_vector(self):
        rows = synthetic_oracle().splitlines()
        rows[1] = rows[0]
        with self.assertRaises(runner.CorrespondenceHeld):
            runner.parse_oracle("\n".join(rows) + "\n")

    def test_oracle_cannot_grant_authority(self):
        raw = synthetic_oracle().replace(
            "E|formallyCheckedModel|0000",
            "E|formallyCheckedModel|0010")
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "DIVERGES"):
            runner.compare(raw)

    def test_oracle_cannot_invent_a_tier(self):
        raw = synthetic_oracle().replace("E|declared|0000", "E|elite|0000")
        with self.assertRaises(runner.CorrespondenceHeld):
            runner.compare(raw)

    def test_oracle_cannot_add_unexpected_output(self):
        with self.assertRaises(runner.CorrespondenceHeld):
            runner.compare(synthetic_oracle() + "PROVED\n")

    def test_oracle_gate_disagreement_detected(self):
        raw = synthetic_oracle().replace("G|1111|1", "G|1111|0")
        with self.assertRaisesRegex(runner.CorrespondenceHeld, "DIVERGES"):
            runner.compare(raw)

    def test_rejects_missing_expected_sha(self):
        with self.assertRaises(runner.CorrespondenceHeld):
            runner.build_receipt(Path("."), None, runner=FakeProcess())

    def test_receipt_pins_sources_and_never_authorizes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for path in runner.SOURCE_PATHS:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture\n", encoding="utf-8")
            (root / "formal/phi-evidence/lean-toolchain").write_text(
                runner.EXPECTED_TOOLCHAIN + "\n", encoding="utf-8")
            report = runner.build_receipt(root, SHA, runner=FakeProcess())
            self.assertEqual(report["comparisons_executed"], 48)
            self.assertEqual(len(report["source_sha256"]), len(runner.SOURCE_PATHS))
            self.assertFalse(report["python_implementation_formally_proven"])
            self.assertFalse(report["actual_privileged_merge_function_exercised"])
            for key in ("code_write_authorized", "worker_dispatch_authorized",
                        "merge_authorized", "deployment_authorized"):
                self.assertFalse(report[key])
            with self.assertRaises(runner.CorrespondenceHeld):
                runner.build_receipt(root, SHA,
                    runner=FakeProcess(sha="c" * 40))
            with self.assertRaises(runner.CorrespondenceHeld):
                runner.build_receipt(root, SHA,
                    runner=FakeProcess(version="Lean (version 4.99.0)"))
            with self.assertRaises(runner.CorrespondenceHeld):
                runner.build_receipt(root, SHA,
                    runner=FakeProcess(failed=[
                        "lake", "env", "lean", "--run", "PolicyOracle.lean"]))
            (root / "scripts/devloop_r2_policy.py").unlink()
            with self.assertRaises(runner.CorrespondenceHeld):
                runner.build_receipt(root, SHA, runner=FakeProcess())


if __name__ == "__main__":
    unittest.main()
