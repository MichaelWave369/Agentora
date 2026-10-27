"""R1-D guided local qualification tests: fake HTTP only, never real Ollama."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest

from app.services.development_board import r1d_field, r1c_cli
from app.services.development_board.r1b_contract import spec_digest
from .test_development_board_r1c import (
    SPEC, fake_local_ollama, fixture_html, ollama_body, spec_path,
)


@contextmanager
def fake_tags(data: bytes, *, status=200, mimetype="application/json"):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Content-Type", mimetype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format, *args):
            pass

    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield service.server_port, calls
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=3)


def test_decline_requires_exact_digest_and_does_not_contact_localhost(tmp_path, monkeypatch):
    source = spec_path(tmp_path)
    contacted = []
    monkeypatch.setattr(r1d_field, "preflight_model", lambda *a: contacted.append(a))
    before = sorted(p.name for p in tmp_path.iterdir())
    for response in ("YES", "APPROVE", "APPROVE " + "0" * 16):
        result = r1d_field.run_guided(source, confirm=lambda prompt: response)
        assert result["status"] == "HELD"
        assert result["reason"] == "OPERATOR_DECLINED_OR_MISMATCHED_ACK"
    assert contacted == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_no_tty_and_keyboard_cancel_are_held(tmp_path):
    source = spec_path(tmp_path)

    def eof(_prompt):
        raise EOFError()

    def keyboard(_prompt):
        raise KeyboardInterrupt()

    for confirmer in (eof, keyboard):
        result = r1d_field.run_guided(source, confirm=confirmer)
        assert result["status"] == "HELD"
        assert result["reason"] == "OPERATOR_DECLINED_OR_NOT_INTERACTIVE"


def test_preflight_fixed_loopback_model_lookup():
    raw = json.dumps({"models": [{"name": "qwen3.5:9b"}]}).encode()
    with fake_tags(raw) as (port, calls):
        result = r1d_field.preflight_model("qwen3.5:9b", port)
        absent = r1d_field.preflight_model("gemma3:12b", port)
    assert calls == ["/api/tags", "/api/tags"]
    assert result == {"status": "READY", "model": "qwen3.5:9b"}
    assert absent["reason"] == "REQUESTED_MODEL_NOT_INSTALLED"


def test_preflight_bad_json_redirect_and_wrong_mime_held():
    for payload, status, mime in [
        (b"not json", 200, "application/json"),
        (b"{}", 302, "application/json"),
        (b"{}", 200, "text/html"),
        (b"x" * 65537, 200, "application/json"),
    ]:
        with fake_tags(payload, status=status, mimetype=mime) as (port, calls):
            result = r1d_field.preflight_model("qwen3.5:9b", port)
        assert result["status"] == "HELD"
        assert len(calls) == 1


def test_guided_field_run_executes_both_workers_after_consent(tmp_path, monkeypatch):
    source = spec_path(tmp_path)
    approved = "APPROVE " + spec_digest(SPEC)[:16]
    with fake_local_ollama(ollama_body(fixture_html())) as (port, calls):
        monkeypatch.setattr(
            r1d_field, "preflight_model",
            lambda model, port: {"status": "READY", "model": model},
        )
        result = r1d_field.run_guided(source, port=port, confirm=lambda prompt: approved)
    assert len(calls) == 1
    assert result["field_result"]["status"] == "LOCAL_RECHECK_PASS_REVIEW_ONLY"
    assert result["field_result"]["classification"] == "LOCAL_SELF_REPORTED_NOT_ATTESTED"
    assert result["field_result"]["human_visual_review"] == "PENDING"
    assert result["field_result"]["code_brown_first_use_test"] == "NOT_PERFORMED"
    assert result["field_result"]["eligible_for_merge"] is False
    location = Path(result["local_workspace"])
    report = location / "field-qualification.json"
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8")) == result["field_result"]
    assert r1d_field.recheck_workspace(location)["status"] == "LOCAL_RECHECK_PASS_REVIEW_ONLY"


def test_preflight_held_prevents_model_calls_and_workspace(tmp_path, monkeypatch):
    source = spec_path(tmp_path)
    monkeypatch.setattr(
        r1d_field, "preflight_model",
        lambda *a: {"status": "HELD", "reason": "REQUESTED_MODEL_NOT_INSTALLED"},
    )
    created = []
    monkeypatch.setattr(
        r1d_field, "run_pilot",
        lambda *a, **kw: created.append((a, kw)),
    )
    result = r1d_field.run_guided(
        source, confirm=lambda prompt: "APPROVE " + spec_digest(SPEC)[:16]
    )
    assert result["status"] == "HELD"
    assert result["reason"] == "REQUESTED_MODEL_NOT_INSTALLED"
    assert created == []
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fixture.json"]


def _valid_workspace(tmp_path):
    source = spec_path(tmp_path)
    with fake_local_ollama(ollama_body(fixture_html())) as (port, calls):
        result = r1c_cli.run_pilot(source, spec_digest(SPEC), port=port, scratch_root=tmp_path)
    assert result["status"] == "REVIEW_READY_NOT_AUTHORIZED", result
    assert len(calls) == 1
    return Path(result["workspace"])


def test_recheck_is_read_only(tmp_path):
    location = _valid_workspace(tmp_path)
    before = sorted(str(path.relative_to(location)) for path in location.rglob("*"))
    result = r1d_field.recheck_workspace(location)
    after = sorted(str(path.relative_to(location)) for path in location.rglob("*"))
    assert result["status"] == "LOCAL_RECHECK_PASS_REVIEW_ONLY", result
    assert result["human_visual_review"] == "NOT_PERFORMED_BY_THIS_TOOL"
    assert result["eligible_for_merge"] is False
    assert before == after


def test_tampered_artifact_is_held(tmp_path):
    location = _valid_workspace(tmp_path)
    artifact = location / "artifact/index.html"
    artifact.write_bytes(artifact.read_bytes() + b"\n<!-- altered -->")
    output = r1d_field.recheck_workspace(location)
    assert output["status"] == "HELD"
    assert output["reason"] == "ARTIFACT_SHA_CHANGED"


def test_untrusted_receipt_override_refused(tmp_path):
    location = _valid_workspace(tmp_path)
    receipt = location / "review-receipt.json"
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["eligible_for_merge"] = True
    receipt.write_text(json.dumps(data), encoding="utf-8")
    output = r1d_field.recheck_workspace(location)
    assert output["status"] == "HELD"
    assert output["reason"] == "RECEIPT_SCOPE_OR_SPEC_MISMATCH"


def test_frozen_spec_change_is_held(tmp_path):
    location = _valid_workspace(tmp_path)
    spec = location / "frozen-spec.json"
    changed = json.loads(spec.read_text(encoding="utf-8"))
    changed["headline"] = "Fake changed headline"
    spec.write_text(json.dumps(changed), encoding="utf-8")
    output = r1d_field.recheck_workspace(location)
    assert output["status"] == "HELD"
    assert output["reason"] == "RECEIPT_SCOPE_OR_SPEC_MISMATCH"


def test_symlink_and_missing_workspace_refused(tmp_path):
    assert r1d_field.recheck_workspace(tmp_path / "missing")["status"] == "HELD"
    real = tmp_path / "directory"
    real.mkdir()
    link = tmp_path / "alias"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable on this platform")
    assert r1d_field.recheck_workspace(link)["reason"] == "WORKSPACE_MISSING_OR_SYMLINK"


def test_guided_cli_no_interactive_flag_to_skip_ack(tmp_path, capsys, monkeypatch):
    source = spec_path(tmp_path)
    monkeypatch.setattr(
        r1d_field, "run_guided", lambda *a, **kw: {"status": "HELD", "reason": "DENIED"}
    )
    assert r1d_field.main(["guided", str(source)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "HELD"


def test_no_web_endpoint_launches_field_cli():
    from .conftest import make_client
    paths = set(make_client().get("/openapi.json").json()["paths"])
    assert not any("development-board" in path and any(
        x in path for x in ("field", "run", "execute", "build", "model")
    ) for path in paths)
