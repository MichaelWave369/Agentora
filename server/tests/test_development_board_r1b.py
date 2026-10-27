"""R1-B real child-process scratch fixture build and independent static checks.

These tests never contact GitHub, Ollama, GitPorch or run generated code.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.services.development_board import r1b_cli
from app.services.development_board.r1b_contract import (
    SCHEMA, frozen_bytes, parse_spec, read_spec, spec_digest, validate_spec,
)
from .conftest import make_client


SPEC = {
    "schema": SCHEMA,
    "title": "A & B workshop",
    "headline": "Proof before promotion",
    "description": "An independent verifier checks the exact artifact.",
    "button_label": "Review & inspect",
}


def write_spec(tmp_path, value=None):
    path = tmp_path / "task-spec.json"
    path.write_text(json.dumps(value if value is not None else SPEC), encoding="utf-8")
    return path


def test_canonical_spec_digest_ignores_object_key_order():
    spec = validate_spec(deepcopy(SPEC))
    reverse = dict(reversed(list(spec.items())))
    assert spec_digest(spec) == spec_digest(reverse)
    assert parse_spec(frozen_bytes(reverse)) == spec


def test_unknown_fields_and_executable_arguments_rejected():
    for key, value in [("command", "rm -rf"), ("output_path", "/tmp/target"),
                       ("allowed_tools", ["shell"]), ("merge_grant", True)]:
        invalid = {**SPEC, key: value}
        with pytest.raises(ValueError, match="INVALID_SPEC_FIELDS"):
            validate_spec(invalid)


def test_bad_control_chars_duplicates_and_huge_spec_refused():
    with pytest.raises(ValueError, match="DUPLICATE_SPEC_KEY"):
        parse_spec(b'{"schema":"x","schema":"y"}')
    with pytest.raises(ValueError, match="SPEC_TOO_LARGE_OR_INVALID"):
        parse_spec(b"x" * 4097)
    with pytest.raises(ValueError, match="INVALID_SPEC_HEADLINE"):
        validate_spec({**SPEC, "headline": "bad\nline"})


def test_plan_only_reads_spec_and_never_creates_workspace(tmp_path):
    source = write_spec(tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    plan = r1b_cli.plan(source)
    assert plan["frozen_spec_digest"] == spec_digest(SPEC)
    assert plan["eligible_for_merge"] is False
    assert plan["model_invocation"] is False
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_wrong_approval_digest_refuses_without_writing_anything(tmp_path):
    source = write_spec(tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    result = r1b_cli.run_pilot(source, "b" * 64, scratch_root=tmp_path)
    assert result["status"] == "HELD"
    assert result["reason"] == "SPEC_DIGEST_DOES_NOT_MATCH_OPERATOR_ACK"
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_two_distinct_os_processes_build_and_verify_fixture(tmp_path):
    source = write_spec(tmp_path)
    result = r1b_cli.run_pilot(source, spec_digest(SPEC), scratch_root=tmp_path)
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    assert result["builder"] != result["verifier"]
    assert result["role_separation"] == "DISTINCT_OS_PROCESSES_NOT_SECURITY_ISOLATION"
    assert result["source_provenance"] == "LOCAL_SELF_REPORTED_UNATTESTED"
    assert result["model_invocation"] is False
    assert result["eligible_for_merge"] is False
    assert result["automatic_merge"] is False
    assert result["role_identity_authenticated"] is False
    workspace = Path(result["workspace"])
    artifact = workspace / "artifact" / "index.html"
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result["artifact_sha256"]
    assert (workspace / "frozen-spec.json").read_bytes() == frozen_bytes(SPEC)
    assert (workspace / "review-receipt.json").is_file()
    assert json.loads((workspace / "review-receipt.json").read_text(encoding="utf-8")) == result
    assert sorted(p.name for p in workspace.iterdir()) == [
        "artifact", "frozen-spec.json", "review-receipt.json",
    ]


def test_user_supplied_markup_is_escaped_and_not_executed(tmp_path):
    hostile = {**SPEC, "headline": '<script>alert("test")</script> & safe',
               "description": '<img src=x onerror=alert(1)> source is untrusted'}
    source = write_spec(tmp_path, hostile)
    result = r1b_cli.run_pilot(source, spec_digest(hostile), scratch_root=tmp_path)
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    html = (Path(result["workspace"]) / "artifact" / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "<img " not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html
    assert result["eligible_for_merge"] is False


def test_independent_verifier_refuses_modified_artifact(tmp_path):
    source = write_spec(tmp_path)
    result = r1b_cli.run_pilot(source, spec_digest(SPEC), scratch_root=tmp_path)
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED"
    workspace = Path(result["workspace"])
    artifact = workspace / "artifact" / "index.html"
    original_sha = result["artifact_sha256"]
    artifact.write_text(artifact.read_text(encoding="utf-8").replace(
        "Proof before promotion", "False success"
    ), encoding="utf-8")
    verdict = r1b_cli.run_worker(
        "r1b_verifier_worker.py",
        [str(workspace / "frozen-spec.json"), str(artifact), original_sha], workspace,
    )
    assert verdict["status"] == "ERROR"
    assert verdict["reason"] == "WORKER_FAILED_OR_OUTPUT_INVALID"


def test_independent_verifier_rejects_malicious_extra_script(tmp_path):
    source = write_spec(tmp_path)
    result = r1b_cli.run_pilot(source, spec_digest(SPEC), scratch_root=tmp_path)
    workspace = Path(result["workspace"])
    artifact = workspace / "artifact" / "index.html"
    artifact.write_text(
        artifact.read_text(encoding="utf-8").replace(
            "</body>", '<script>bad()</script></body>'
        ), encoding="utf-8"
    )
    new_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    verdict = r1b_cli.run_worker(
        "r1b_verifier_worker.py",
        [str(workspace / "frozen-spec.json"), str(artifact), new_hash], workspace,
    )
    assert verdict["status"] == "ERROR"


def test_builder_cannot_overwrite_existing_artifact(tmp_path):
    source = write_spec(tmp_path)
    result = r1b_cli.run_pilot(source, spec_digest(SPEC), scratch_root=tmp_path)
    workspace = Path(result["workspace"])
    artifact = workspace / "artifact" / "index.html"
    before = artifact.read_bytes()
    again = r1b_cli.run_worker(
        "r1b_builder_worker.py",
        [str(workspace / "frozen-spec.json"), str(workspace / "artifact")], workspace,
    )
    assert again["status"] == "ERROR"
    assert artifact.read_bytes() == before


def test_artifact_change_after_verification_refused(tmp_path, monkeypatch):
    source = write_spec(tmp_path)
    real_worker = r1b_cli.run_worker

    def tamper_after_verification(script, args, workspace):
        result = real_worker(script, args, workspace)
        if script == "r1b_verifier_worker.py" and result.get("status") == "STATIC_CHECKS_PASS_SELF_REPORTED":
            file = Path(workspace) / "artifact" / "index.html"
            file.write_bytes(file.read_bytes() + b"\n<!-- tampered -->")
        return result

    monkeypatch.setattr(r1b_cli, "run_worker", tamper_after_verification)
    result = r1b_cli.run_pilot(source, spec_digest(SPEC), scratch_root=tmp_path)
    assert result["status"] == "HELD"
    assert result["reason"] == "ARTIFACT_CHANGED_DURING_VERIFICATION"


def test_cli_requires_explicit_ack_and_does_not_authorize_merge(tmp_path, capsys):
    source = write_spec(tmp_path)
    code = r1b_cli.main([
        "run", str(source), "--approve-spec-digest", spec_digest(SPEC)
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 2
    assert result["status"] == "HELD"
    assert result["reason"] == "EXPLICIT_LOCAL_FIXTURE_APPROVAL_REQUIRED"


def test_live_http_surface_does_not_dispatch_fixture_processes():
    client = make_client()
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/development-board/handoff/preview" in paths
    assert not any("/development-board" in path and
                   ("run" in path or "execute" in path or "build" in path)
                   for path in paths)
