"""Cloud model decision lane with fake local Ollama: no real downloads or secrets."""
import hashlib
import json
from pathlib import Path

import pytest

from app.services.development_board import r1e_cloud, r1f_cloud_theme, r1f_theme_worker
from app.services.development_board.r1b_contract import read_spec, spec_digest
from .test_development_board_r1c import fake_local_ollama


def theme_reply(choice="arcade"):
    return json.dumps({
        "message": {"role": "assistant", "content": json.dumps({"theme": choice})},
        "done": True,
    }).encode("utf-8")


def test_model_choice_is_small_single_field_schema():
    spec = read_spec(r1e_cloud.SPEC_PATH)
    payload = json.loads(r1f_theme_worker.payload(spec))
    assert payload["model"] == "qwen3:0.6b"
    assert payload["think"] is False
    assert payload["format"]["properties"]["theme"]["enum"] == [
        "arcade", "aurora", "slate"
    ]
    assert payload["options"]["num_predict"] <= 100
    assert not any(word in payload["messages"][0]["content"] for word in ("execute", "shell", "deploy"))


def test_one_inference_then_distinct_verifier_and_offline_recheck(tmp_path):
    spec = read_spec(r1e_cloud.SPEC_PATH)
    digest = spec_digest(spec)
    with fake_local_ollama(theme_reply("arcade")) as (port, calls):
        result = r1f_cloud_theme.run_theme_pilot(
            r1e_cloud.SPEC_PATH, digest, model="qwen3:0.6b",
            port=port, scratch_root=tmp_path,
        )
    assert len(calls) == 1
    request = json.loads(calls[0]["body"])
    assert calls[0]["path"] == "/api/chat"
    assert request["model"] == "qwen3:0.6b"
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    assert result["model_contribution"] == "BOUNDED_THEME_ENUM_ONLY"
    assert result["theme"] == "arcade"
    assert result["eligible_for_merge"] is False
    assert result["automatic_merge"] is False
    assert result["verifier"] == "independent-fixture-verifier-process"
    workspace = Path(result["workspace"])
    artifact = workspace / "artifact/index.html"
    assert b"#241637" in artifact.read_bytes()
    assert artifact.is_file()
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result["artifact_sha256"]
    check = r1f_cloud_theme.recheck_theme(workspace)
    assert check["status"] == "LOCAL_RECHECK_PASS_REVIEW_ONLY", check
    assert check["theme"] == "arcade"
    assert check["eligible_for_merge"] is False


def test_failed_model_proposal_shows_safe_reason_and_uploads_no_untrusted_html(tmp_path):
    with fake_local_ollama(theme_reply("user-injected-custom")) as (port, calls):
        held = r1f_cloud_theme.run_theme_pilot(
            r1e_cloud.SPEC_PATH, spec_digest(read_spec(r1e_cloud.SPEC_PATH)),
            model="qwen3:0.6b", port=port, scratch_root=tmp_path,
        )
    assert held["status"] == "HELD"
    assert held["reason"] == "MODEL_CHOICE_NOT_ALLOWED", held
    assert held["failed_stage"] == "MODEL_OR_TEMPLATE"
    assert len(calls) == 1
    output = tmp_path / "out"
    output.mkdir()
    cloud = r1e_cloud.run_cloud(
        "ollama_cpu", output, model_runner=lambda *a, **kw: held
    )
    assert cloud["status"] == "HELD"
    assert cloud["bounded_origin_reason"] == "MODEL_CHOICE_NOT_ALLOWED"
    assert cloud["origin_stage"] == "MODEL_OR_TEMPLATE"
    assert sorted(x.name for x in output.iterdir()) == ["cloud-report.json"]


def test_model_no_html_code_or_unsafe_link_enters_artifact():
    spec = read_spec(r1e_cloud.SPEC_PATH)
    for theme in sorted(r1f_theme_worker.THEMES):
        markup = r1f_theme_worker.render_theme(spec, theme)
        assert b"<!doctype html>" in markup
        assert b"data-spec-sha256" in markup
        assert b"<script" not in markup
        assert b"http://" not in markup
        assert b"https://" not in markup
        assert b"javascript:" not in markup
        assert b"onclick" not in markup
    with pytest.raises(r1f_theme_worker.SafeThemeError):
        r1f_theme_worker.render_theme(spec, "<script>alert(1)</script>")


def test_corrupt_ollama_response_and_http_status_are_categorized(tmp_path):
    bad_responses = [
        (b"bad json", 200, "MODEL_RESPONSE_NOT_VALID_JSON"),
        (theme_reply("nope"), 200, "MODEL_CHOICE_NOT_ALLOWED"),
        (theme_reply("aurora"), 500, "MODEL_HTTP_NOT_OK"),
    ]
    for raw, status, code in bad_responses:
        with fake_local_ollama(raw, status=status) as (port, calls):
            result = r1f_cloud_theme.run_theme_pilot(
                r1e_cloud.SPEC_PATH,
                spec_digest(read_spec(r1e_cloud.SPEC_PATH)),
                model="qwen3:0.6b", port=port, scratch_root=tmp_path,
            )
        assert len(calls) == 1
        assert result["status"] == "HELD"
        assert result["reason"] == code
        assert result["failed_stage"] == "MODEL_OR_TEMPLATE"


def test_wrong_model_or_digest_fails_without_creating_scratch(tmp_path):
    original = list(tmp_path.iterdir())
    for model, digest in [("wrong:model", "b" * 64), ("qwen3:0.6b", "b" * 64)]:
        result = r1f_cloud_theme.run_theme_pilot(
            r1e_cloud.SPEC_PATH, digest,
            model=model, port=11434, scratch_root=tmp_path,
        )
        assert result["status"] == "HELD"
        assert result["failed_stage"] == "PRECHECK"
    assert list(tmp_path.iterdir()) == original


def test_tampered_saved_artifact_recheck_refuses(tmp_path):
    with fake_local_ollama(theme_reply("slate")) as (port, _):
        result = r1f_cloud_theme.run_theme_pilot(
            r1e_cloud.SPEC_PATH,
            spec_digest(read_spec(r1e_cloud.SPEC_PATH)),
            model="qwen3:0.6b", port=port, scratch_root=tmp_path,
        )
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    workspace = Path(result["workspace"])
    with (workspace / "artifact/index.html").open("ab") as f:
        f.write(b"\n<!-- modified -->")
    assert r1f_cloud_theme.recheck_theme(workspace)["status"] == "HELD"


def test_direct_cloud_mode_works_with_real_fake_server(tmp_path):
    # Cloud controller invokes the new theme pipeline, not R1-C freeform HTML.
    with fake_local_ollama(theme_reply("aurora")) as (port, calls):
        def runner(path, digest, **args):
            return r1f_cloud_theme.run_theme_pilot(
                path, digest, model=args["model"], port=port, scratch_root=tmp_path
            )
        output = tmp_path / "artifacts"
        output.mkdir()
        result = r1e_cloud.run_cloud("ollama_cpu", output, model_runner=runner)
    assert len(calls) == 1
    assert result["status"] == "STATIC_REVIEW_READY_NOT_AUTHORIZED", result
    assert result["model_contribution"] == "BOUNDED_THEME_ENUM_ONLY"
    assert result["theme"] == "aurora"
    assert result["deterministic_markup_builder"] is True
    assert result["eligible_for_merge"] is False
    assert (output / "untrusted-model-proposal.html.txt").is_file()
    assert not (output / "index.html").exists()


def test_forged_theme_and_authority_refused_by_cloud_gate(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    def forged(*a, **kw):
        return {
            "status": "REVIEW_READY_NOT_AUTHORIZED",
            "spec_digest": spec_digest(read_spec(r1e_cloud.SPEC_PATH)),
            "artifact": "artifact/index.html", "model": "qwen3:0.6b",
            "theme": "../untrusted", "model_contribution": "BOUNDED_THEME_ENUM_ONLY",
            "eligible_for_merge": False, "automatic_merge": False,
            "repository_writes": "NONE",
        }
    result = r1e_cloud.run_cloud("ollama_cpu", out, model_runner=forged)
    assert result["status"] == "HELD"
    assert result["reason"] == "MODEL_IDENTITY_OR_OUTPUT_UNVERIFIED"
    assert sorted(f.name for f in out.iterdir()) == ["cloud-report.json"]
