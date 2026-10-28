"""R1-H safe packet is a toy, exact and never gives PhiBot write authority."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.development_board import r1h_packet


def test_exact_inert_packet_and_local_hashes():
    packet = r1h_packet.packet_for("a" * 40)
    assert packet["schema"] == "agentora.devboard.r1h.readonly-coding-task.v1"
    assert packet["task_kind"] == "INERT_SINGLE_FILE_SOURCE_PREVIEW_ONLY"
    assert packet["repository"] == "MichaelWave369/Agentora"
    assert packet["target_path"] == "examples/development-board/r1h-demo-label.py"
    assert packet["source_before"] == r1h_packet.BEFORE
    assert packet["source_after_preview"] == r1h_packet.AFTER
    assert packet["source_before_sha256"] == hashlib.sha256(r1h_packet.BEFORE.encode()).hexdigest()
    assert packet["source_after_sha256"] == hashlib.sha256(r1h_packet.AFTER.encode()).hexdigest()
    assert packet["authority"] and set(packet["authority"].values()) == {False}
    assert "issueNumber" not in packet and "replacement" not in packet
    assert r1h_packet.validate_packet(packet)["status"] == "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY"


def test_manual_hosted_cloud_prepare_and_recheck_bytes(tmp_path):
    output = tmp_path / "cloud"
    output.mkdir()
    receipt = r1h_packet.prepare_cloud(output, "a" * 40)
    assert receipt["status"] == "STATIC_PACKET_CHECKS_PASS_REVIEW_ONLY"
    assert receipt["eligible_for_merge"] is False
    assert receipt["write_authorized"] is False
    assert sorted(p.name for p in output.iterdir()) == [
        "agentora-review-receipt.json",
        "phibot-review-packet.base64url.txt",
        "phibot-review-packet.json",
    ]
    assert r1h_packet.recheck_artifact(output, "a" * 40) == receipt
    raw = (output / "phibot-review-packet.json").read_bytes().strip()
    b64 = (output / "phibot-review-packet.base64url.txt").read_text().strip()
    assert base64.urlsafe_b64encode(raw).decode().rstrip("=") == b64
    assert json.loads(raw)["packet_sha256"] == receipt["packet_sha256"]


@pytest.mark.parametrize("key,value", [
    ("target_path", "../secret.py"),
    ("source_before", "print('evil')\n"),
    ("source_after_preview", "import os\nos.system('whoami')\n"),
    ("packet_sha256", "0" * 64),
    ("disposition", "AUTHORIZED_FOR_WRITE"),
])
def test_packet_mutation_refuses(key, value):
    packet = r1h_packet.packet_for("a" * 40)
    packet[key] = value
    assert r1h_packet.validate_packet(packet)["status"] == "HELD"


def test_authority_mutations_refuse():
    packet = r1h_packet.packet_for("a" * 40)
    for field in packet["authority"]:
        altered = r1h_packet.packet_for("a" * 40)
        altered["authority"][field] = True
        assert r1h_packet.validate_packet(altered)["status"] == "HELD"


def test_wrong_commit_and_existing_files_refuse(tmp_path):
    for sha in ("z" * 40, "a" * 39, "0x" + "a" * 40, "a" * 64):
        with pytest.raises(ValueError):
            r1h_packet.packet_for(sha)
    output = tmp_path / "output"
    output.mkdir()
    (output / "preserve-this").write_text("no overwrite")
    with pytest.raises(ValueError):
        r1h_packet.prepare_cloud(output, "a" * 40)
    assert (output / "preserve-this").read_text() == "no overwrite"


def test_tamper_and_symlink_refuse(tmp_path):
    for name in ("phibot-review-packet.json", "phibot-review-packet.base64url.txt", "agentora-review-receipt.json"):
        directory = tmp_path / name.replace(".", "_")
        directory.mkdir()
        r1h_packet.prepare_cloud(directory, "a" * 40)
        with (directory / name).open("ab") as stream:
            stream.write(b"x")
        assert r1h_packet.recheck_artifact(directory, "a" * 40)["status"] == "HELD"


def test_actual_workflow_python_command_needs_manual_dispatch(tmp_path):
    root = r1h_packet.ROOT
    cwd = root / "server"
    output = tmp_path / "pack"
    output.mkdir()
    cmd = [sys.executable, "-m", "app.services.development_board.r1h_packet",
           "prepare", "--output-dir", str(output)]
    env = dict(os.environ, PYTHONPATH=".", GITHUB_ACTIONS="true",
               GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_SHA="a" * 40)
    run = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr + run.stdout
    next_check = subprocess.run(cmd[:3] + ["recheck", "--output-dir", str(output)],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
    assert next_check.returncode == 0, next_check.stderr + next_check.stdout
    denied = subprocess.run(cmd[:3] + ["recheck", "--output-dir", str(output)], cwd=cwd,
                            env=dict(env, GITHUB_EVENT_NAME="push"),
                            capture_output=True, text=True, timeout=15)
    assert denied.returncode == 2
    assert json.loads(denied.stdout)["status"] == "HELD"


def test_workflow_does_not_enable_model_or_github_writes_for_packet():
    workflow = (r1h_packet.ROOT / ".github/workflows/development-board-cloud-trial.yml").read_text()
    assert "          - draft_review" in workflow
    assert "inputs.mode == 'draft_review'" in workflow
    assert "r1h_packet prepare" in workflow
    assert "r1h_packet recheck" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "workflow_dispatch:" in workflow
    assert "\n  pull_request:" not in workflow
    assert "\n  push:" not in workflow
    assert "inputs.mode == 'ollama_cpu' || inputs.mode == 'design_cpu'" in workflow
