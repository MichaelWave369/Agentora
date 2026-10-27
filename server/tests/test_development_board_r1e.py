"""R1-E cloud run is manual-only, scope bounded and never merge-authoritative."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.development_board import r1e_cloud
from app.services.development_board.r1b_contract import read_spec, spec_digest


def test_public_fixture_path_is_fixed_and_plan_is_inert(tmp_path):
    assert r1e_cloud.SPEC_PATH.is_file()
    before = list(tmp_path.iterdir())
    plan = r1e_cloud.plan_cloud("fixture")
    assert plan["trigger"] == "MANUAL_WORKFLOW_DISPATCH_ONLY"
    assert plan["mode"] == "fixture"
    assert plan["frozen_spec_sha256"] == spec_digest(read_spec(r1e_cloud.SPEC_PATH))
    assert plan["model_download"] is False
    assert plan["eligible_for_merge"] is False
    assert list(tmp_path.iterdir()) == before


def test_cloud_fixture_runs_actual_separate_builder_and_verifier(tmp_path):
    output = tmp_path / "cloud-output"
    output.mkdir()
    result = r1e_cloud.run_cloud("fixture", output, head_sha="a" * 40)
    assert result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED", result
    assert result["eligible_for_merge"] is False
    assert result["automatic_merge"] is False
    assert result["github_writes"] == "NONE"
    assert result["github_deploy"] == "NONE"
    assert result["qualification"] == "GITHUB_HOSTED_SELF_REPORTED_NOT_ATTESTED"
    assert result["human_visual_review"] == "NOT_PERFORMED"
    assert result["mode"] == "fixture"
    assert sorted(path.name for path in output.iterdir()) == [
        "cloud-report.json", "frozen-spec.json", "index.html",
    ]
    artifact = (output / "index.html").read_bytes()
    assert hashlib.sha256(artifact).hexdigest() == result["artifact_sha256"]
    assert json.loads((output / "cloud-report.json").read_text()) == result


def test_cloned_invalid_model_result_cannot_create_green_artifact(tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    def held_model(*args, **kwargs):
        return {
            "status": "HELD", "workspace": str(tmp_path / "untrusted"),
            "artifact": "artifact/index.html",
        }

    result = r1e_cloud.run_cloud("ollama_cpu", out, model_runner=held_model)
    assert result["status"] == "HELD"
    assert sorted(x.name for x in out.iterdir()) == ["cloud-report.json"]
    assert result["eligible_for_merge"] is False


def test_model_claimed_pass_without_independent_recheck_is_held(tmp_path):
    source = tmp_path / "model-workspace"
    artifact_dir = source / "artifact"
    artifact_dir.mkdir(parents=True)
    raw = b"<!doctype html>not verified"
    (artifact_dir / "index.html").write_bytes(raw)
    current_sha = hashlib.sha256(raw).hexdigest()
    spec = read_spec(r1e_cloud.SPEC_PATH)
    digest = spec_digest(spec)

    def fake_model(*args, **kwargs):
        return {
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "workspace": str(source),
            "artifact": "artifact/index.html",
            "artifact_sha256": current_sha,
            "spec_digest": digest,
            "model": "qwen3:0.6b",
            "model_output": "UNTRUSTED_STATIC_HTML_PROPOSAL",
            "eligible_for_merge": False,
            "automatic_merge": False,
            "repository_writes": "NONE",
        }

    output = tmp_path / "output"
    output.mkdir()
    result = r1e_cloud.run_cloud(
        "ollama_cpu", output, model_runner=fake_model,
        rechecker=lambda p: {"status": "HELD"},
    )
    assert result["status"] == "HELD"
    assert result["reason"] == "INDEPENDENT_RECHECK_HELD"
    assert sorted(p.name for p in output.iterdir()) == ["cloud-report.json"]


def test_successful_simulated_model_recheck_exports_text_not_browser_html(tmp_path):
    source = tmp_path / "model-workspace"
    artifact_dir = source / "artifact"
    artifact_dir.mkdir(parents=True)
    raw = b"<!doctype html>bounded but untrusted candidate"
    (artifact_dir / "index.html").write_bytes(raw)
    current_sha = hashlib.sha256(raw).hexdigest()
    digest = spec_digest(read_spec(r1e_cloud.SPEC_PATH))

    def simulated_runner(*args, **kwargs):
        return {
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "workspace": str(source),
            "artifact": "artifact/index.html",
            "artifact_sha256": current_sha,
            "spec_digest": digest,
            "model": "qwen3:0.6b",
            "model_output": "UNTRUSTED_STATIC_HTML_PROPOSAL",
            "eligible_for_merge": False,
            "automatic_merge": False,
            "repository_writes": "NONE",
        }

    def simulated_recheck(*_args):
        return {
            "status": "LOCAL_RECHECK_PASS_REVIEW_ONLY",
            "artifact_sha256": current_sha,
            "spec_digest": digest,
            "eligible_for_merge": False,
        }

    output = tmp_path / "output"
    output.mkdir()
    result = r1e_cloud.run_cloud(
        "ollama_cpu", output,
        model_runner=simulated_runner, rechecker=simulated_recheck,
    )
    assert result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED"
    assert result["artifact_export"] == "untrusted-model-proposal.html.txt"
    assert (output / "untrusted-model-proposal.html.txt").read_bytes() == raw
    assert not (output / "index.html").exists()
    assert result["eligible_for_merge"] is False


def test_tampered_output_filename_scope_fails_closed(tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    def forged_runner(*args, **kwargs):
        return {
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "workspace": "/tmp/nowhere",
            "artifact": "../../source/README.md",
            "spec_digest": spec_digest(read_spec(r1e_cloud.SPEC_PATH)),
            "eligible_for_merge": False,
            "automatic_merge": False,
        }

    result = r1e_cloud.run_cloud("fixture", out, fixed_runner=forged_runner)
    assert result["status"] == "HELD"
    assert sorted(p.name for p in out.iterdir()) == ["cloud-report.json"]


def test_no_arbitrary_mode_or_nonempty_export_destination(tmp_path):
    with pytest.raises(ValueError, match="UNKNOWN_CLOUD_MODE"):
        r1e_cloud.plan_cloud("execute")
    with pytest.raises(ValueError, match="UNKNOWN_CLOUD_MODE"):
        r1e_cloud.run_cloud("unknown", tmp_path)
    (tmp_path / "already-there.txt").write_text("existing")
    with pytest.raises(ValueError, match="OUTPUT_DIRECTORY_MUST_BE_EMPTY"):
        r1e_cloud.run_cloud("fixture", tmp_path)


def test_cli_refuses_non_manual_context_and_writes_no_files(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    path = tmp_path / "cloud-out"
    path.mkdir()
    rc = r1e_cloud.main(["run", "--mode", "fixture", "--output-dir", str(path)])
    response = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert response["reason"] == "MANUAL_GITHUB_ACTIONS_DISPATCH_REQUIRED"
    assert list(path.iterdir()) == []


def test_workflow_is_manual_only_least_permission_and_uploads_no_held_html():
    workflow = r1e_cloud.ROOT / ".github/workflows/development-board-cloud-trial.yml"
    content = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in content
    assert "\n  pull_request:" not in content
    assert "\n  push:" not in content
    assert "schedule:" not in content
    assert "contents: read" in content
    assert "persist-credentials: false" in content
    assert "actions/upload-artifact@v4" in content
    assert "docker exec devboard-cloud-ollama ollama pull qwen3:0.6b" in content
    assert "if: " + "$" + "{{ always() }}" in content
    assert "workflow_dispatch" in content


def test_hosted_workflow_runs_python_from_actual_server_package_root():
    """Guard the precise workflow regression: repository-root app.py shadows app/."""
    workflow = r1e_cloud.ROOT / ".github/workflows/development-board-cloud-trial.yml"
    lines = workflow.read_text(encoding="utf-8")
    assert "PYTHONPATH: ." in lines
    assert lines.count("working-directory: server") == 3
    assert "mkdir -p ../cloud-artifacts" in lines
    assert "--mode fixture --output-dir ../cloud-artifacts" in lines
    assert "--mode ollama_cpu --output-dir ../cloud-artifacts" in lines
    assert (r1e_cloud.ROOT / "app.py").is_file()  # shadows the package when run at repo root
    assert (r1e_cloud.ROOT / "server/app/__init__.py").is_file()


def test_exact_python_module_launch_from_hosted_working_directory(tmp_path):
    """Actually execute BOTH plan and builder/verifier, as the Actions shell does."""
    import os
    server = r1e_cloud.ROOT / "server"
    env = dict(os.environ, PYTHONPATH=".", GITHUB_ACTIONS="true",
               GITHUB_EVENT_NAME="workflow_dispatch",
               PYTHONDONTWRITEBYTECODE="1")
    command = [sys.executable, "-m", "app.services.development_board.r1e_cloud"]
    plan = subprocess.run(
        command + ["plan", "--mode", "fixture"], cwd=server,
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert plan.returncode == 0, plan.stderr
    assert json.loads(plan.stdout)["mode"] == "fixture"
    output = tmp_path / "cloud-artifacts"
    output.mkdir()
    run = subprocess.run(
        command + ["run", "--mode", "fixture", "--output-dir", str(output)],
        cwd=server, env=env, capture_output=True, text=True, timeout=30,
    )
    assert run.returncode == 0, run.stderr + run.stdout
    receipt = json.loads((output / "cloud-report.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED"
    assert receipt["eligible_for_merge"] is False
    assert (output / "index.html").is_file()
    assert hashlib.sha256((output / "index.html").read_bytes()).hexdigest() == receipt["artifact_sha256"]
