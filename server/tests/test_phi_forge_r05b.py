import importlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
b = importlib.import_module("phi_forge_r05b")
a = importlib.import_module("phi_forge_r05a")
r3 = b.r3
TARGET = "web/src/components/Nav.tsx"
BEFORE = "export default function Nav(){return <nav/>}\n"
AFTER = 'export default function Nav(){return <nav aria-label="Main"/>}\n'
MODEL = "test:local"


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / "source"
    target = source / TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes(BEFORE.encode())
    (source / ".gitignore").write_text(".env\n")
    (source / ".env").write_text("PRIVATE_MARKER")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True)
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "fixture")
    task = r3.initialize(source, tmp_path / "spec.json", TARGET,
                         "Improve navigation accessibility label.", "forge-proposal-test")
    return task, source, MODEL, tmp_path / "candidate"


def test_real_git_to_r05a_plan(fixture, tmp_path):
    plan, payload, _ = b.prepare(*fixture)
    assert "PRIVATE_MARKER" not in str(payload)
    assert "tools" not in payload
    ask = Mock(return_value={"content": AFTER, "summary": "Label"})
    result = b.generate(*fixture, b.plan_digest(plan), True, ask=ask)
    assert result["state"] == "CANDIDATE_REVIEW_REQUIRED"
    assert not result["build_authorized"] and not result["eligible_for_merge"]
    assert (fixture[1] / TARGET).read_bytes() == BEFORE.encode()
    assert json.loads((fixture[3] / "proposal-receipt.json").read_text()) == result
    cache = tmp_path / "cache"
    cache.mkdir()
    next_plan, _ = a.prepare(fixture[0], fixture[1], fixture[3] / "replacement.tsx",
                              "sha256:" + "a"*64, cache)
    assert next_plan["proposal"]["patch_sha256"] == result["proposal"]["patch_sha256"]
    assert next_plan["state"] == "REVIEW_REQUIRED"
    ask.assert_called_once_with(payload)


@pytest.mark.parametrize("offline,changed", [(False, False), (True, True)])
def test_approval_refusal(fixture, offline, changed):
    plan, _, _ = b.prepare(*fixture)
    ask = Mock()
    approved = "0"*64 if changed else b.plan_digest(plan)
    with pytest.raises(b.Held):
        b.generate(*fixture, approved, offline, ask=ask)
    ask.assert_not_called()
    assert not fixture[3].exists()


def test_model_change_refused(fixture):
    plan, _, _ = b.prepare(*fixture)
    ask = Mock()
    with pytest.raises(b.Held):
        b.generate(fixture[0], fixture[1], "other:local", fixture[3],
                   b.plan_digest(plan), True, ask=ask)
    ask.assert_not_called()


@pytest.mark.parametrize("model", ["x:cloud", "https://remote:1", "untagged"])
def test_model_invalid(fixture, model):
    with pytest.raises(b.Held):
        b.prepare(fixture[0], fixture[1], model, fixture[3])


def test_output_fences(fixture):
    task, source, model, out = fixture
    with pytest.raises(b.Held):
        b.prepare(task, source, model, source / "candidate")
    out.mkdir()
    with pytest.raises(b.Held):
        b.prepare(*fixture)


def test_drift_after_inference(fixture):
    plan, _, _ = b.prepare(*fixture)
    def ask(_):
        (fixture[1] / TARGET).write_text(AFTER)
        return {"content": AFTER, "summary": "Label"}
    with pytest.raises(b.Held):
        b.generate(*fixture, b.plan_digest(plan), True, ask=ask)
    assert not fixture[3].exists()


@pytest.mark.parametrize("response", [{"content": BEFORE, "summary": "no change"},
    {"content": AFTER, "summary": "label", "command": "run"},
    {"content": AFTER.rstrip(), "summary": "no newline"}])
def test_invalid_candidate(fixture, response):
    plan, _, _ = b.prepare(*fixture)
    with pytest.raises(b.Held):
        b.generate(*fixture, b.plan_digest(plan), True, ask=lambda _: response)
    assert not fixture[3].exists()


def test_provider_checks(fixture):
    _, payload, _ = b.prepare(*fixture)
    data = {"done": True, "model": MODEL, "message": {"role": "assistant",
            "content": json.dumps({"content": AFTER, "summary": "label"})}}
    with patch.object(b, "HTTPConnection") as factory:
        conn = factory.return_value
        response = conn.getresponse.return_value
        response.status = 200
        response.getheader.side_effect = lambda k, default: "application/json" if k == "Content-Type" else default
        response.read.return_value = json.dumps(data).encode()
        assert b.request_model(payload)["content"] == AFTER
        factory.assert_called_once_with("127.0.0.1", 11434, timeout=120)
        assert conn.request.call_args.args[:2] == ("POST", "/api/chat")
        for change in (dict(data, done=False), dict(data, model="other:local"),
                       dict(data, message=dict(data["message"], tool_calls=[{}]))):
            response.read.return_value = json.dumps(change).encode()
            with pytest.raises(b.Held):
                b.request_model(payload)
        response.status = 302
        with pytest.raises(b.Held):
            b.request_model(payload)
