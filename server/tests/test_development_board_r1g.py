"""R1-G model selects bounded design only; fake localhost protocol, real child processes."""
import hashlib
import json
from pathlib import Path

import pytest

from app.services.development_board import (
    r1e_cloud, r1g_cloud_design, r1g_design_worker, r1g_design_verifier,
)
from app.services.development_board.r1b_contract import read_spec, spec_digest
from app.services.development_board.r1b_verifier_worker import verify_fixture
from .test_development_board_r1c import fake_local_ollama

SPEC = read_spec(r1e_cloud.SPEC_PATH)
DIGEST = spec_digest(SPEC)
DEMO = {"theme": "arcade", "layout": "split", "focus": "handoff"}


def response(design=DEMO):
    return json.dumps({
        "message": {"content": json.dumps(design)}, "done": True,
    }).encode("utf-8")


def test_small_model_schema_is_exactly_three_allowlisted_decisions():
    payload = json.loads(r1g_design_worker.model_payload(SPEC))
    assert payload["model"] == "qwen3:0.6b"
    assert payload["stream"] is False and payload["think"] is False
    assert payload["format"]["additionalProperties"] is False
    assert payload["format"]["required"] == ["theme", "layout", "focus"]
    assert payload["options"]["num_predict"] <= 160
    assert set(payload["format"]["properties"]) == {"theme", "layout", "focus"}
    for key, variants in r1g_design_worker.CHOICES.items():
        assert payload["format"]["properties"][key]["enum"] == sorted(variants)


def test_every_approved_combination_is_deterministic_and_r1b_valid():
    outputs = set()
    for theme in sorted(r1g_design_worker.THEMES):
        for layout in sorted(r1g_design_worker.LAYOUTS):
            for focus in sorted(r1g_design_worker.FOCUSES):
                choice = {"theme": theme, "layout": layout, "focus": focus}
                html = r1g_design_worker.render_design(SPEC, choice)
                assert html == r1g_design_worker.render_design(SPEC, choice)
                assert verify_fixture(SPEC, html, hashlib.sha256(html).hexdigest())[
                    "status"] == "STATIC_CHECKS_PASS_SELF_REPORTED"
                assert f'data-theme="{theme}"'.encode() in html
                assert f'data-layout="{layout}"'.encode() in html
                assert f'data-focus="{focus}"'.encode() in html
                assert r1g_design_worker.FOCUS_COPY[focus][0].encode() in html
                assert r1g_design_worker.LAYOUT_CSS[layout].encode() in html
                assert b"<script" not in html and b"javascript:" not in html
                outputs.add(hashlib.sha256(html).hexdigest())
    assert len(outputs) == 27


def test_real_subprocess_from_fake_ollama_checks_two_verifiers_and_rechecks(tmp_path):
    with fake_local_ollama(response()) as (port, calls):
        result = r1g_cloud_design.run_design_pilot(
            r1e_cloud.SPEC_PATH, DIGEST,
            model="qwen3:0.6b", port=port, scratch_root=tmp_path,
        )
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/chat"
    request = json.loads(calls[0]["body"])
    assert request["model"] == "qwen3:0.6b"
    assert request["format"]["required"] == ["theme", "layout", "focus"]
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    assert result["choices"] == DEMO
    assert result["eligible_for_merge"] is False
    assert result["automatic_merge"] is False
    assert result["repository_writes"] == "NONE"
    assert result["html_verifier"] == "independent-fixture-verifier-process"
    assert result["design_verifier"] == "independent-process-exact-design-contract-verifier"
    workspace = Path(result["workspace"])
    assert (workspace / "artifact/index.html").is_file()
    assert (workspace / "design-decision.json").is_file()
    checked = r1g_cloud_design.recheck_design(workspace)
    assert checked["status"] == "LOCAL_RECHECK_PASS_REVIEW_ONLY", checked
    assert checked["choices"] == DEMO


def test_cloud_controller_manual_model_lane_outputs_four_safe_files(tmp_path):
    with fake_local_ollama(response({"theme": "slate", "layout": "cards", "focus": "audit"})) as (port, calls):
        def runner(spec, digest, **kwargs):
            return r1g_cloud_design.run_design_pilot(
                spec, digest, model=kwargs["model"], port=port, scratch_root=tmp_path
            )
        folder = tmp_path / "export"
        folder.mkdir()
        result = r1e_cloud.run_cloud(
            "design_cpu", folder, design_runner=runner, head_sha="f" * 40,
        )
    assert len(calls) == 1
    assert result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED", result
    assert result["model_contribution"] == "THREE_BOUNDED_ENUM_DECISIONS_ONLY"
    assert result["design_choices"] == {"theme": "slate", "layout": "cards", "focus": "audit"}
    assert result["eligible_for_merge"] is False
    assert result["github_writes"] == "NONE"
    assert result["github_deploy"] == "NONE"
    assert sorted(path.name for path in folder.iterdir()) == [
        "cloud-report.json", "design-decision.json", "frozen-spec.json",
        "untrusted-design-proposal.html.txt",
    ]
    assert not (folder / "index.html").exists()
    assert json.loads((folder / "cloud-report.json").read_text()) == result
    text = (folder / "untrusted-design-proposal.html.txt").read_text()
    assert "data-layout=\"cards\"" in text


@pytest.mark.parametrize("bad_choice", [
    {"theme": "aurora", "layout": "split", "focus": "<script>"},
    {"theme": "slate", "layout": "../../etc", "focus": "audit"},
    {"theme": "aurora", "layout": "split", "focus": "audit", "code": "exec"},
    {"theme": "aurora", "focus": "audit"},
    {"theme": True, "layout": "cards", "focus": "audit"},
])
def test_model_refusal_never_exports_html(tmp_path, bad_choice):
    with fake_local_ollama(response(bad_choice)) as (port, calls):
        pilot = r1g_cloud_design.run_design_pilot(
            r1e_cloud.SPEC_PATH, DIGEST, model="qwen3:0.6b",
            port=port, scratch_root=tmp_path,
        )
    assert len(calls) == 1
    assert pilot["status"] == "HELD", pilot
    assert pilot["failed_stage"] == "MODEL_OR_RENDERER"
    export = tmp_path / "export"
    export.mkdir()
    result = r1e_cloud.run_cloud("design_cpu", export, design_runner=lambda *a, **k: pilot)
    assert result["status"] == "HELD"
    assert result["origin_stage"] == "MODEL_OR_RENDERER"
    assert result["bounded_origin_reason"] in (
        "DESIGN_FIELDS_INVALID", "DESIGN_CHOICE_NOT_ALLOWED",
    )
    assert sorted(p.name for p in export.iterdir()) == ["cloud-report.json"]


def test_model_bad_json_or_http_error_refuses_with_bounded_code(tmp_path):
    for raw, code, status in [
        (b"oops", "MODEL_RESPONSE_NOT_JSON", 200),
        (response(DEMO), "MODEL_HTTP_NOT_OK", 403),
    ]:
        with fake_local_ollama(raw, status=status) as (port, _):
            outcome = r1g_cloud_design.run_design_pilot(
                r1e_cloud.SPEC_PATH, DIGEST,
                model="qwen3:0.6b", port=port, scratch_root=tmp_path,
            )
        assert outcome["status"] == "HELD"
        assert outcome["reason"] == code


def test_changed_spec_and_wrong_model_refuse_before_network_or_files(tmp_path):
    previous = list(tmp_path.iterdir())
    for digest, model in [("0" * 64, "qwen3:0.6b"), (DIGEST, "other")]:
        output = r1g_cloud_design.run_design_pilot(
            r1e_cloud.SPEC_PATH, digest, model=model,
            port=11434, scratch_root=tmp_path,
        )
        assert output["status"] == "HELD"
        assert output["failed_stage"] == "PRECHECK"
    assert list(tmp_path.iterdir()) == previous


def test_tamper_artifact_and_decision_fail_recheck(tmp_path):
    with fake_local_ollama(response()) as (port, _):
        receipt = r1g_cloud_design.run_design_pilot(
            r1e_cloud.SPEC_PATH, DIGEST,
            model="qwen3:0.6b", port=port, scratch_root=tmp_path,
        )
    assert receipt["status"] == "REVIEW_READY_NOT_AUTHORIZED", receipt
    workspace = Path(receipt["workspace"])
    artifact = workspace / "artifact/index.html"
    original = artifact.read_bytes()
    artifact.write_bytes(original + b"<!-- modified -->")
    assert r1g_cloud_design.recheck_design(workspace)["status"] == "HELD"
    artifact.write_bytes(original)
    decision = workspace / "design-decision.json"
    data = json.loads(decision.read_text())
    data["choices"]["layout"] = "cards"
    decision.write_text(json.dumps(data))
    assert r1g_cloud_design.recheck_design(workspace)["status"] == "HELD"


def test_decision_contract_refuses_wrong_markup_even_with_new_matching_sha():
    original = r1g_design_worker.render_design(SPEC, DEMO)
    forged = original.replace(b'data-layout="split"', b'data-layout="cards"')
    decision = {
        "schema": "agentora.devboard.r1g.decision.v1",
        "model": "qwen3:0.6b", "spec_digest": DIGEST,
        "choices": DEMO, "authority": "NONE",
        "model_contribution": "THREE_BOUNDED_ENUM_DECISIONS_ONLY",
    }
    with pytest.raises(ValueError, match="ARTIFACT_NOT_EXACT_APPROVED_DESIGN"):
        r1g_design_verifier.verify_design(
            SPEC, decision, forged, hashlib.sha256(forged).hexdigest()
        )


def test_workflow_preserves_existing_modes_and_opt_in():
    workflow = (r1e_cloud.ROOT / ".github/workflows/development-board-cloud-trial.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow and "\n  pull_request:" not in workflow
    assert "          - fixture" in workflow
    assert "          - ollama_cpu" in workflow
    assert "          - design_cpu" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "working-directory: server" in workflow
    assert "--mode design_cpu --output-dir ../cloud-artifacts" in workflow
    assert "inputs.mode == 'design_cpu'" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert r1e_cloud.plan_cloud("fixture")["mode"] == "fixture"
    assert r1e_cloud.plan_cloud("ollama_cpu")["mode"] == "ollama_cpu"
    assert r1e_cloud.plan_cloud("design_cpu")["mode"] == "design_cpu"
