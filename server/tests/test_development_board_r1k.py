"""R1-K nine-organ pilot: declaration != demonstration != authority."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.development_board import r1k_sovereign_cell as cell


def raw_doc():
    return cell.MANIFEST.read_bytes()


def parsed_doc():
    return json.loads(raw_doc())


def encode(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def test_real_manifest_inventory_finds_all_organs_and_explicit_gaps():
    report = cell.inspect(raw_doc(), cell.ROOT, "a" * 40)
    assert report["schema"] == "agentora.devboard.r1k.sovereign-cell-review.v1"
    assert report["status"] == "NINE_ORGANS_DECLARED_REVIEW_ONLY"
    assert report["organs_declared"] == 9
    assert report["principles_checked"] == 9
    assert report["evidence_files_present"] == 9
    assert list(report["tiers_declared"]) == ["being", "function", "sovereignty"]
    assert all(v == "DECLARED_NOT_OPERATIONALLY_CERTIFIED"
               for v in report["tiers_declared"].values())
    assert {"one_runtime", "one_recovery_path", "easy_to_restore"}.issubset(
        report["unmet_or_unproven_principles"]
    )
    assert report["readiness"] == "NOT_SOVEREIGN_QUALIFIED"
    for name in ("model_executed", "repository_writes", "deployment_executed",
                 "release_authorized", "eligible_for_merge", "automatic_merge"):
        assert report[name] is False
    assert report["human_review_required"] is True
    for item in report["evidence_file_sha256"]:
        assert len(item["sha256"]) == 64
        assert item["sha256"] == hashlib.sha256(
            (cell.ROOT / item["path"]).read_bytes()
        ).hexdigest()
    assert cell.verify_receipt(raw_doc(), cell.ROOT, "a" * 40, report)


@pytest.mark.parametrize("bad", ["", "ABC" * 14, "b" * 39, "f" * 41])
def test_commit_refused(bad):
    with pytest.raises(cell.CellRefusal, match="COMMIT_PIN_REFUSED"):
        cell.inspect(raw_doc(), cell.ROOT, bad)


@pytest.mark.parametrize("mutation,code", [
    (lambda x: x.update({"schema": "phi369.sovereign-cell.manifest.v9"}),
     "MANIFEST_SCHEMA_REFUSED"),
    (lambda x: x["tiers"]["being"].remove("memory"), "NINE_ORGAN_TIER_MAPPING_REFUSED"),
    (lambda x: x["organs"].pop("shield"), "NINE_ORGANS_REQUIRED"),
    (lambda x: x["principles"].pop("secure_by_default"), "NINE_PRINCIPLES_REQUIRED"),
    (lambda x: x["principles"]["one_runtime"].update({"assessment": "EVIDENCED_CLAIM_ONLY"}),
     "UNVERIFIED_SOVEREIGNTY_CLAIM_REFUSED"),
    (lambda x: x["principles"]["easy_to_restore"].update({"assessment": "PARTIAL"}),
     "UNVERIFIED_SOVEREIGNTY_CLAIM_REFUSED"),
    (lambda x: x["principles"]["local_first"].update({"assessment": "EVIDENCED_CLAIM_ONLY"}),
     "LOCAL_FIRST_OVERCLAIM_REFUSED"),
    (lambda x: x["authority"].update({"repository_write": True}),
     "AUTHORITY_ESCALATION_REFUSED"),
    (lambda x: x["authority"].update({"automatic_merge": 1}),
     "AUTHORITY_ESCALATION_REFUSED"),
    (lambda x: x["authority"].update({"github_token": "never"}),
     "AUTHORITY_ESCALATION_REFUSED"),
    (lambda x: x["declared_architecture"].update({"single_process": "VERIFIED"}),
     "RUNTIME_CLAIM_REFUSED"),
    (lambda x: x["cell"].update({"maturity_claim": "CERTIFIED"}),
     "CELL_IDENTITY_REFUSED"),
])
def test_untrusted_manifest_mutations_fail_closed(mutation, code):
    document = parsed_doc()
    mutation(document)
    with pytest.raises(cell.CellRefusal, match=code):
        cell.parse_manifest(encode(document))


@pytest.mark.parametrize("evil_path", [
    "../private.key",
    "/etc/passwd",
    "docs/../../private.env",
    "docs/.",
    "docs//thing.md",
    "docs/thing\\secret",
    ".github/workflows/../../../etc/passwd",
    "http://evil.example/code",
    "config/secrets.env",
])
def test_paths_reject_traversal_or_non_allowlisted(evil_path):
    document = parsed_doc()
    document["organs"]["memory"]["evidence_paths"] = [evil_path]
    with pytest.raises(cell.CellRefusal, match="ORGAN_EVIDENCE_PATH_REFUSED"):
        cell.parse_manifest(encode(document))


def test_missing_and_symlink_file_are_not_evidence(tmp_path):
    doc = parsed_doc()
    for organ in cell.ORGANS:
        for ref in doc["organs"][organ]["evidence_paths"]:
            file = tmp_path / ref
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("dummy evidence bytes\n")
    report = cell.inspect(encode(doc), tmp_path, "a" * 40)
    assert report["evidence_files_present"] == 9
    victim = tmp_path / doc["organs"]["body"]["evidence_paths"][0]
    victim.unlink()
    with pytest.raises(cell.CellRefusal, match="EVIDENCE_FILE_MISSING"):
        cell.inspect(encode(doc), tmp_path, "a" * 40)
    victim.symlink_to(tmp_path / "secrets.txt")
    with pytest.raises(cell.CellRefusal, match="EVIDENCE_SYMLINK_REFUSED"):
        cell.inspect(encode(doc), tmp_path, "a" * 40)


def test_manifest_data_immutability_and_receipt_rechecks():
    raw = raw_doc()
    report = cell.inspect(raw, cell.ROOT, "a" * 40)
    wrong = copy.deepcopy(report)
    wrong["eligible_for_merge"] = True
    assert not cell.verify_receipt(raw, cell.ROOT, "a" * 40, wrong)
    wrong = copy.deepcopy(report)
    wrong["evidence_file_sha256"][0]["sha256"] = "0" * 64
    assert not cell.verify_receipt(raw, cell.ROOT, "a" * 40, wrong)
    assert not cell.verify_receipt(raw, cell.ROOT, "b" * 40, report)


def test_do_not_enforce_phi_or_numeric_covenants_as_security_thresholds():
    text = raw_doc().decode("utf-8")
    for phrase in ("0.809", "0.618", "0.376", "369_369", "Sigil", "Parallax"):
        assert phrase not in text
    assert not hasattr(cell, "GOLDEN_RATIO_CI_PASS")
    assert cell.parse_manifest(raw_doc())["cell"]["maturity_claim"] == (
        "DESIGN_PILOT_NOT_SOVEREIGN_CERTIFIED"
    )


def test_actual_cloud_cli_and_manual_gate(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    cmd = [sys.executable, "-m", "app.services.development_board.r1k_sovereign_cell",
           "--output-dir", str(out)]
    environment = {
        **os.environ, "PYTHONPATH": "server", "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "a" * 40,
    }
    first = subprocess.run(cmd, cwd=cell.ROOT, env=environment,
                           capture_output=True, text=True, timeout=20)
    assert first.returncode == 0, first.stderr + first.stdout
    exported = json.loads((out / "sovereign-cell-review.json").read_text())
    assert exported["status"] == "NINE_ORGANS_DECLARED_REVIEW_ONLY"
    assert exported["repository_writes"] is False
    # Fail rather than overwrite any previous operator review artifact.
    again = subprocess.run(cmd, cwd=cell.ROOT, env=environment,
                           capture_output=True, text=True, timeout=20)
    assert again.returncode == 2
    assert (out / "sovereign-cell-review.json").is_file()
    new = tmp_path / "new"
    new.mkdir()
    denied = subprocess.run(cmd[:-1] + [str(new)], cwd=cell.ROOT,
                            env={**environment, "GITHUB_EVENT_NAME": "push"},
                            capture_output=True, text=True, timeout=20)
    assert denied.returncode == 2
    assert not list(new.iterdir())


def test_manual_github_workflow_boundaries():
    workflow = (cell.ROOT / ".github/workflows/development-board-sovereign-cell.yml").read_text()
    for required in ("workflow_dispatch:", "contents: read",
                     "persist-credentials: false",
                     "r1k_sovereign_cell --output-dir",
                     "sovereign-cell-review.json"):
        assert required in workflow
    for forbidden in ("\n  pull_request:", "\n  push:", "\n  schedule:",
                      "docker run", "gh api", "GITHUB_TOKEN:"):
        assert forbidden not in workflow
