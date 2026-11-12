"""Agentora Neural Research R1: offline, proposal-only PhiStream experiment planner.

All inputs are operator-supplied and self-reported. This module performs no
training, subprocess calls, imports of experiment code, network requests,
model loading, approval, scheduling, PR writes, or deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = "agentora.neural.proposal.v1"
REVIEW_SCHEMA = "agentora.neural.review.v1"
PLAN_SCHEMA = "PHI_NEURAL_PLAN_R1"
RECEIPT_SCHEMA = "PHI_NEURAL_LAB_R1"
META_SCHEMA = "PHI_TINY_TRAIN_R1"
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_DATASET_BYTES = 1024 * 1024
HEX = re.compile(r"[a-f0-9]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
METRIC = re.compile(r"^(val_bpb|training_seconds|total_seconds|peak_vram_mb|num_steps|num_params_M):\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*$")
CONFIG_KEYS = {"context", "dim", "heads", "layers", "batch", "steps", "lr", "seconds", "vram_mb", "seed", "device", "study_id", "run_id"}
PLAN_KEYS = {"schema", "study_id", "run_id", "engine", "metric", "direction", "dataset_sha256", "evaluator_sha256", "tokenizer_sha256", "hardware_id", "training_budget_seconds", "max_peak_vram_mb", "source_ref"}
COMPARE_KEYS = ("engine", "metric", "direction", "dataset_sha256", "evaluator_sha256", "tokenizer_sha256", "hardware_id", "training_budget_seconds")
TUNABLE = {"lr": (0.000001, 0.03), "dim": (8, 256), "heads": (1, 8), "layers": (1, 4), "batch": (1, 16)}


class ResearchHeld(ValueError):
    """Evidence or proposal cannot cross the review-only boundary."""


def need(condition, reason):
    if not condition:
        raise ResearchHeld(reason)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def bounded_file(path, size_limit=MAX_INPUT_BYTES):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "SOURCE_NOT_REGULAR_FILE")
    size = path.stat().st_size
    need(0 < size <= size_limit, "SOURCE_SIZE_INVALID")
    return path.read_bytes()


def read_json(path):
    try:
        value = json.loads(bounded_file(path).decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ResearchHeld("SOURCE_JSON_INVALID") from exc
    need(type(value) is dict, "SOURCE_OBJECT_REQUIRED")
    return value


def finite(value, label, *, positive=False):
    need(type(value) in (float, int) and math.isfinite(value), "NUMBER_INVALID_" + label)
    if positive:
        need(value > 0, "NUMBER_NOT_POSITIVE_" + label)
    return float(value)


def close(a, b, tolerance=1e-8):
    return math.isclose(finite(a, "FIRST"), finite(b, "SECOND"), rel_tol=1e-9, abs_tol=tolerance)


def validate_config(cfg):
    need(type(cfg) is dict and set(cfg) == CONFIG_KEYS, "CONFIG_FIELDS_INVALID")
    for key, lo, hi in (("context", 4, 128), ("dim", 8, 256), ("heads", 1, 8),
                        ("layers", 1, 4), ("batch", 1, 16), ("steps", 1, 1000),
                        ("seed", 1, 2**31 - 1)):
        need(type(cfg[key]) is int and lo <= cfg[key] <= hi, "CONFIG_BOUND_" + key.upper())
    need(cfg["dim"] % cfg["heads"] == 0, "ATTENTION_DIM_NOT_DIVISIBLE")
    for key, lo, hi in (("lr", 0.0, 0.03), ("seconds", 1, 3600), ("vram_mb", 256, 24576)):
        value = finite(cfg[key], key, positive=True)
        need(lo < value <= hi if key == "lr" else lo <= value <= hi, "CONFIG_BOUND_" + key.upper())
    need(cfg["device"] in ("cpu", "cuda"), "DEVICE_INVALID")
    for key in ("study_id", "run_id"):
        need(type(cfg[key]) is str and NAME.fullmatch(cfg[key]), "CONFIG_ID_INVALID")
    return cfg


def validate_plan(plan):
    need(type(plan) is dict and set(plan) == PLAN_KEYS, "PLAN_FIELDS_INVALID")
    need(plan["schema"] == PLAN_SCHEMA and plan["engine"] == "phi_tiny" and
         plan["metric"] == "val_bpb" and plan["direction"] == "min" and
         plan["source_ref"] == "PhiStream:phistream/neural_tiny.py", "PLAN_CONTRACT_INVALID")
    for key in ("study_id", "run_id", "hardware_id"):
        need(type(plan[key]) is str and NAME.fullmatch(plan[key]), "PLAN_ID_INVALID")
    for key in ("dataset_sha256", "evaluator_sha256", "tokenizer_sha256"):
        need(type(plan[key]) is str and HEX.fullmatch(plan[key]), "PLAN_DIGEST_INVALID")
    for key in ("training_budget_seconds", "max_peak_vram_mb"):
        finite(plan[key], key, positive=True)
    return plan


def validate_receipt(r):
    need(type(r) is dict and r.get("schema") == RECEIPT_SCHEMA, "RECEIPT_SCHEMA_INVALID")
    observed = r.get("receipt_sha256")
    need(type(observed) is str and HEX.fullmatch(observed), "RECEIPT_DIGEST_INVALID")
    need(digest({k: v for k, v in r.items() if k != "receipt_sha256"}) == observed, "RECEIPT_CHANGED")
    validate_plan(r.get("plan"))
    need(r.get("admissible") is True and r.get("reasons") == [] and
         r.get("assurance") == "self_declared_context_and_byte_integrity_only" and
         r.get("promotion") == "human_review_required", "RECEIPT_NOT_ADMISSIBLE")
    need(type(r.get("metrics")) is dict, "RECEIPT_METRICS_INVALID")
    for key in ("code_sha256", "log_sha256"):
        need(type(r.get(key)) is str and HEX.fullmatch(r[key]), "RECEIPT_FILE_DIGEST_INVALID")
    return r


def parse_log(raw):
    try:
        source = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ResearchHeld("LOG_ENCODING_INVALID") from exc
    values = {}
    for line in source.splitlines():
        match = METRIC.fullmatch(line.strip())
        if match:
            key, val = match.groups()
            need(key not in values, "METRIC_DUPLICATED")
            try:
                values[key] = finite(float(val), key)
            except ValueError as exc:
                raise ResearchHeld("METRIC_MALFORMED") from exc
    need({"val_bpb", "training_seconds", "total_seconds", "peak_vram_mb", "num_steps"}.issubset(values), "METRIC_MISSING")
    need(values["val_bpb"] > 0 and values["training_seconds"] > 0 and
         values["total_seconds"] >= values["training_seconds"] and
         values["peak_vram_mb"] >= 0 and
         values["num_steps"] > 0 and values["num_steps"].is_integer(), "METRIC_RANGE_INVALID")
    return values


def inspect_baseline(meta, receipt, data_bytes, log_bytes, code_bytes):
    """Compare operator-supplied artifacts; cannot authenticate physical training."""
    need(type(meta) is dict and meta.get("schema") == META_SCHEMA and
         meta.get("status") == "LOCAL_TRAINING_COMPLETED_UNVERIFIED", "META_SCHEMA_INVALID")
    need(meta.get("production_authorized") is False and
         meta.get("quality_improvement_proven") is False and
         meta.get("training_proven_authentic") is False and
         meta.get("checkpoint_saved") is False and
         meta.get("network_used") is False, "META_AUTHORITY_INVALID")
    cfg = validate_config(meta.get("config"))
    plan = validate_plan(meta.get("plan"))
    receipt = validate_receipt(receipt)
    need(receipt["plan"] == plan, "BASELINE_PLAN_NOT_BOUND")
    need(cfg["study_id"] == plan["study_id"] and cfg["run_id"] == plan["run_id"] and
         plan["hardware_id"].startswith(cfg["device"] + "-"), "BASELINE_CONTEXT_INVALID")
    need(close(cfg["seconds"], plan["training_budget_seconds"]) and
         close(cfg["vram_mb"], plan["max_peak_vram_mb"]), "BASELINE_LIMITS_DIFFER")
    need(200 <= len(data_bytes) <= MAX_DATASET_BYTES and
         hashlib.sha256(data_bytes).hexdigest() == plan["dataset_sha256"], "DATASET_MISMATCH")
    try:
        data = data_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ResearchHeld("DATASET_NOT_UTF8") from exc
    need("\x00" not in data, "DATASET_UNSAFE")
    need(hashlib.sha256(code_bytes).hexdigest() == receipt["code_sha256"] == meta.get("train_code_sha256"), "TRAINER_CODE_CHANGED")
    need(hashlib.sha256(log_bytes).hexdigest() == receipt["log_sha256"], "METRIC_LOG_CHANGED")
    metrics = parse_log(log_bytes)
    need(set(receipt["metrics"]) == set(metrics), "RECEIPT_LOG_METRICS_DIFFER")
    for key, val in metrics.items():
        need(close(receipt["metrics"][key], val), "RECEIPT_METRIC_CHANGED")
    need(metrics["num_steps"] == cfg["steps"] == meta.get("steps") and
         close(metrics["val_bpb"], meta.get("final_val_bpb")), "META_METRIC_MISMATCH")
    need(metrics["training_seconds"] <= cfg["seconds"] * 1.05 and
         metrics["peak_vram_mb"] <= cfg["vram_mb"], "BUDGET_EXCEEDED")
    return {"config": cfg, "plan": plan, "receipt": receipt, "metrics": metrics}


def load_baseline(args):
    return inspect_baseline(read_json(args.meta), read_json(args.receipt),
                            bounded_file(args.data, MAX_DATASET_BYTES),
                            bounded_file(args.log), bounded_file(args.code))


def parse_change(parameter, value):
    need(parameter in TUNABLE, "PARAMETER_NOT_ALLOWLISTED")
    try:
        val = float(value) if parameter == "lr" else int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchHeld("PROPOSED_VALUE_INVALID") from exc
    if parameter != "lr":
        need(str(val) == str(value), "PROPOSED_INTEGER_NOT_CANONICAL")
    low, high = TUNABLE[parameter]
    need(math.isfinite(val) and low <= val <= high, "PROPOSED_VALUE_OUTSIDE_LIMITS")
    return val


def propose(base, parameter, value):
    val = parse_change(parameter, value)
    cfg = dict(base["config"])
    old = cfg[parameter]
    need(val != old, "NO_CHANGE_PROPOSED")
    cfg[parameter] = val
    validate_config(cfg)
    basis = {"receipt_sha256": base["receipt"]["receipt_sha256"],
             "parameter": parameter, "value": val}
    candidate_id = "trial-" + digest(basis)[:16]
    cfg["run_id"] = candidate_id
    proposal = {
        "schema": SCHEMA,
        "status": "REVIEW_ONLY_NOT_DISPATCHABLE",
        "baseline": {
            "study_id": base["plan"]["study_id"],
            "run_id": base["plan"]["run_id"],
            "receipt_sha256": base["receipt"]["receipt_sha256"],
            "trainer_code_sha256": base["receipt"]["code_sha256"],
            "metric_val_bpb": base["metrics"]["val_bpb"],
            "steps": base["config"]["steps"],
        },
        "change": {"parameter": parameter, "before": old, "after": val},
        "candidate": cfg,
        "comparison_contract": {key: base["plan"][key] for key in COMPARE_KEYS},
        "limits": {"execution_authorized": False, "github_write_authorized": False,
                   "auto_merge_authorized": False, "model_promotion_authorized": False,
                   "requires_operator_training_approval": True,
                   "requires_separate_reponerve_verification": True},
    }
    proposal["proposal_sha256"] = digest(proposal)
    return proposal


def verify_proposal(proposal, base):
    need(type(proposal) is dict and type(proposal.get("change")) is dict,
         "PROPOSAL_STRUCTURE_INVALID")
    expected = propose(base, proposal["change"].get("parameter"),
                       str(proposal["change"].get("after")))
    need(proposal == expected, "PROPOSAL_CHANGED_OR_BASELINE_STALE")
    return {"schema": "agentora.neural.verify.v1", "status": "MATCHES_DECLARED_BASELINE",
            "proposal_sha256": proposal["proposal_sha256"],
            "execution_authorized": False, "review_required": True}


def assess(base, proposal, candidate_receipt, *, min_delta=0.001):
    """Read-only advisory; RepoNerve must still verify each candidate evidence file."""
    verify_proposal(proposal, base)
    candidate = validate_receipt(candidate_receipt)
    need(type(min_delta) in (int, float) and math.isfinite(min_delta) and
         0 <= min_delta <= 1, "MIN_DELTA_INVALID")
    plan = candidate["plan"]
    need(plan["study_id"] == proposal["baseline"]["study_id"] and
         plan["run_id"] == proposal["candidate"]["run_id"], "CANDIDATE_ID_MISMATCH")
    need(all(plan[k] == v for k,v in proposal["comparison_contract"].items()),
         "CANDIDATE_EVALUATION_CONTEXT_CHANGED")
    need(candidate["code_sha256"] == proposal["baseline"]["trainer_code_sha256"],
         "CANDIDATE_TRAINER_CODE_CHANGED")
    step_count = finite(candidate["metrics"].get("num_steps"), "num_steps", positive=True)
    need(step_count.is_integer() and step_count == proposal["baseline"]["steps"],
         "CANDIDATE_TRAINING_STEPS_CHANGED")
    bpb = finite(candidate["metrics"].get("val_bpb"), "val_bpb", positive=True)
    delta = base["metrics"]["val_bpb"] - bpb
    # This is a proposed review signal, not proof of quality or reliable improvement.
    return {"schema": REVIEW_SCHEMA, "state":
            "CANDIDATE_FOR_INDEPENDENT_REVIEW" if delta > min_delta else "NO_CLEAR_MEASURED_GAIN",
            "baseline_receipt_sha256": base["receipt"]["receipt_sha256"],
            "candidate_receipt_sha256": candidate["receipt_sha256"],
            "delta_val_bpb": round(delta, 10),
            "minimum_delta": float(min_delta),
            "independent_replay_completed": False,
            "candidate_evidence_files_reverified": False,
            "model_promotion_authorized": False,
            "merge_authorized": False}


def write_new(path, payload):
    path = Path(path)
    need(not path.exists() and not path.is_symlink() and path.parent.is_dir(),
         "OUTPUT_MUST_BE_NEW_IN_EXISTING_DIRECTORY")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agentora neural research planner (offline, proposal only)")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "propose", "verify", "assess"):
        p = sub.add_parser(command)
        for key in ("meta", "receipt", "data", "log", "code"):
            p.add_argument("--" + key, type=Path, required=True)
        if command == "propose":
            p.add_argument("--parameter", choices=sorted(TUNABLE), required=True)
            p.add_argument("--value", required=True)
            p.add_argument("--out", type=Path)
        if command in ("verify", "assess"):
            p.add_argument("--proposal", type=Path, required=True)
        if command == "assess":
            p.add_argument("--candidate-receipt", type=Path, required=True)
            p.add_argument("--min-delta", type=float, default=0.001)
    args = parser.parse_args(argv)
    try:
        base = load_baseline(args)
        if args.command == "preflight":
            report = {"schema": "agentora.neural.preflight.v1",
                      "status": "SELF_REPORTED_EVIDENCE_CONSISTENT_REVIEW_ONLY",
                      "study_id": base["plan"]["study_id"],
                      "baseline_run_id": base["plan"]["run_id"],
                      "baseline_receipt_sha256": base["receipt"]["receipt_sha256"],
                      "training_started": False, "network_used": False,
                      "hardware_authenticated": False, "execution_authorized": False}
        elif args.command == "propose":
            report = propose(base, args.parameter, args.value)
            if args.out is not None:
                write_new(args.out, report)
        elif args.command == "verify":
            report = verify_proposal(read_json(args.proposal), base)
        else:
            report = assess(base, read_json(args.proposal),
                            read_json(args.candidate_receipt), min_delta=args.min_delta)
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ResearchHeld, OSError, OverflowError) as exc:
        parser.exit(2, "neural research HELD: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())