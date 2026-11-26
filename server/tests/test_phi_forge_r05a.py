"""Synthetic R05-A tests; actual Git fixture, no Docker daemon or model required."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
forge = importlib.import_module("phi_forge_r05a")
r3 = forge.r3
IMAGE = "sha256:" + "a" * 64
TARGET = "web/src/components/Nav.tsx"
BEFORE = "export default function Nav(){return <nav/>}\n"
AFTER = 'export default function Nav(){return <nav aria-label="Main"/>}\n'


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / "source"
    target = source / TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes(BEFORE.encode())
    (source / ".gitignore").write_text(".env\n")
    (source / ".env").write_text("PRIVATE_ONLY")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "fixture")
    cache = tmp_path / "cache"
    cache.mkdir()
    replacement = tmp_path / "replacement.tsx"
    replacement.write_bytes(AFTER.encode())
    spec = tmp_path / "spec.json"
    task = r3.initialize(source, spec, TARGET, "Improve navigation accessibility label.", "forge-local-test")
    return task, source, replacement, IMAGE, cache


def test_plan_no_docker_and_exact_diff(fixture):
    plan, after = forge.prepare(*fixture)
    assert after == AFTER
    assert plan["proposal"]["target_path"] == TARGET
    assert "aria-label" in plan["proposal"]["patch"]
    assert not plan["eligible_for_merge"]


@pytest.mark.parametrize("offline,approved", [(False, "bad"), (True, "bad")])
def test_refuses_unapproved(fixture, offline, approved):
    runner = Mock()
    with pytest.raises(forge.Held):
        forge.run_approved(*fixture, approved, offline, runner=runner)
    runner.assert_not_called()


def test_changed_replacement_refuses(fixture):
    plan, _ = forge.prepare(*fixture)
    fixture[2].write_bytes(AFTER.replace("Main", "Other").encode())
    runner = Mock()
    with pytest.raises(forge.Held):
        forge.run_approved(*fixture, forge.plan_digest(plan), True, runner=runner)
    runner.assert_not_called()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_isolated_build(fixture, exit_code, monkeypatch):
    plan, _ = forge.prepare(*fixture)
    monkeypatch.setenv("GH_TOKEN", "PRIVATE")
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2375")
    monkeypatch.setenv("HTTP_PROXY", "http://remote.invalid")
    def fake(args, **kwargs):
        assert args[:2] == ["docker", "--host"]
        assert args[2].startswith(("unix://", "npipe://"))
        for token in ("--pull=never", "--network", "none", "--read-only",
                      "--cap-drop", "ALL", "--entrypoint", IMAGE):
            assert token in args
        assert "--offline" in args[-1] and "--ignore-scripts" in args[-1]
        assert "GH_TOKEN" not in kwargs["env"] and "DOCKER_HOST" not in kwargs["env"]
        assert "HTTP_PROXY" not in kwargs["env"]
        candidate = Path(next(v for v in args if "dst=/src" in v).split("src=", 1)[1].split(",dst=")[0])
        assert (candidate / TARGET).read_bytes() == AFTER.encode()
        assert not (candidate / ".env").exists()
        return SimpleNamespace(returncode=exit_code)
    runner = Mock(side_effect=fake)
    receipt = forge.run_approved(*fixture, forge.plan_digest(plan), True, runner=runner)
    assert receipt["state"] == ("BUILD_PASS_REVIEW_ONLY" if exit_code == 0 else "HELD")
    assert receipt["offline_verified"] is False and receipt["eligible_for_merge"] is False
    assert (fixture[1] / TARGET).read_bytes() == BEFORE.encode()
    runner.assert_called_once()


def test_bad_image_or_cache(fixture):
    task, source, replacement, _, cache = fixture
    with pytest.raises(forge.Held):
        forge.prepare(task, source, replacement, "node:latest", cache)
    with pytest.raises(forge.Held):
        forge.prepare(task, source, replacement, IMAGE, source)


def test_dirty_checkout_refused(fixture):
    (fixture[1] / TARGET).write_bytes(AFTER.encode())
    with pytest.raises(forge.Held):
        forge.prepare(*fixture)
