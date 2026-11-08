"""PhiConstruct R4 controller tests. Never execute Docker or untrusted Python."""
import contextlib
import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
import pytest
from scripts import construct_training_worker as w

CANDIDATE = "a"*40
CONTROLLER = "b"*40
HANDOFF = "sha256:"+"c"*64
IMAGE = "python:3.12-alpine@sha256:"+"d"*64


class FakeDocker:
    def __init__(self, mode="pass"):
        self.mode = mode
        self.calls = []
    def __call__(self, argv, **kwargs):
        assert argv[:2] == ["docker", "run"]
        self.calls.append(argv)
        mount = next(x for x in argv if x.startswith("--mount="))
        root = Path(mount.split(",src=",1)[1].split(",dst=",1)[0])
        inp = json.loads((root/"input.json").read_text(encoding="utf-8"))
        assert (root/"candidate.py").is_file()
        assert (root/"wrapper.py").is_file()
        if self.mode == "timeout":
            raise subprocess.TimeoutExpired(argv, w.TIMEOUT)
        if self.mode == "malformed":
            data = "untrusted output\n"
        elif self.mode == "wrong":
            data = '__PHI_R4__{"value":false}\n'
        else:
            arg = inp["args"][0]
            if inp["function"] == "retry_delay":
                value = min(16,2**max(0,arg))
            else:
                value = re.sub("[^a-z0-9]+","-",arg.strip().lower()).strip("-")
            data = "__PHI_R4__"+json.dumps({"value":value})+"\n"
        kwargs["stdout"].write(data.encode("utf-8"))
        kwargs["stdout"].flush()
        return SimpleNamespace(returncode=0)


def setup_candidate(tmp_path, task="retry-backoff-code"):
    root=tmp_path/"candidate"
    folder=root/"construct_candidates"
    folder.mkdir(parents=True)
    (folder/(task+".py")).write_text("def retry_delay(x): return 1\n",encoding="utf-8")
    return root


def pre(task="retry-backoff-code"):
    return w.prepare(task,CANDIDATE,HANDOFF,IMAGE,CONTROLLER,w.CONFIRM)


def run_example(tmp_path,task="retry-backoff-code",mode="pass"):
    root=setup_candidate(tmp_path,task)
    fake=FakeDocker(mode)
    result=w.run(task,CANDIDATE,HANDOFF,IMAGE,CONTROLLER,pre(task),root,
       observed_controller_sha=CONTROLLER,observed_candidate_sha=CANDIDATE,runner=fake)
    return result,fake


def test_task_manifest_identity_and_digest():
    for name in w.TASKS:
        task=w.task_for(name)
        assert task["id"]==name
        assert task["pack_id"]=="core.repo-evidence"
        assert len(task["cases"])==7
        assert len(w.digest(w.encode(task)))==71


@pytest.mark.parametrize("update",[
 {"confirmation":"EXECUTE_ANYTHING"},
 {"candidate_sha":"main"},
 {"controller_sha":"f"*39},
 {"handoff_digest":"sha1:bad"},
 {"image":"python:latest"},
 {"image":"evil.example/python@sha256:"+"a"*64}
])
def test_bad_preflight_fails_closed(update):
    values=dict(task_id="retry-backoff-code",candidate_sha=CANDIDATE,
        handoff_digest=HANDOFF,image=IMAGE,controller_sha=CONTROLLER,
        confirmation=w.CONFIRM)
    values.update(update)
    with pytest.raises(w.WorkerHeld):
        w.prepare(**values)


def test_docker_args_restricted(tmp_path):
    cmd=w.docker_argv(IMAGE,tmp_path/"data",tmp_path/"cid")
    for text in ("--network=none","--read-only","--cap-drop=ALL",
        "--security-opt=no-new-privileges","--user=65534:65534",
        "--pids-limit=32","--memory=128m","--pull=never"):
        assert text in cmd
    assert "--privileged" not in cmd
    assert "/var/run/docker.sock" not in " ".join(cmd)
    assert any(v.startswith("--mount=type=bind") and "readonly" in v for v in cmd)


@pytest.mark.parametrize("task",["retry-backoff-code","repo-slug-code"])
def test_fixed_container_diagnostic_is_never_authorization(tmp_path,task):
    result,fake=run_example(tmp_path,task)
    assert result["state"]=="BOUNDED_CHECKS_PASSED"
    assert result["passed_count"]==result["total_cases"]==7
    assert len(fake.calls)==7
    assert result["task_digest"]==pre(task)["task_digest"]
    assert result["candidate_file_digest"].startswith("sha256:")
    for field in ("pack_approval_independently_verified",
        "github_artifact_digest_independently_verified",
        "remote_worker_lease_attested","agent_identity_authenticated",
        "general_competence_verified","execution_authorized_after_training",
        "dispatch_authorized","merge_authorized","deployment_authorized"):
        assert result[field] is False


@pytest.mark.parametrize("mode",["wrong","malformed"])
def test_untrusted_container_output_cannot_claim_success(tmp_path,mode):
    result,_=run_example(tmp_path,mode=mode)
    assert result["state"]=="BOUNDED_CHECKS_FAILED"
    assert result["passed_count"] < 7
    assert result["general_competence_verified"] is False


def test_timeout_is_held(tmp_path):
    with pytest.raises(w.WorkerHeld,match="CONTAINER_RUN"):
        run_example(tmp_path,mode="timeout")


def test_pinned_preflight_and_sha_fencing(tmp_path):
    root=setup_candidate(tmp_path)
    forged={**pre(),"merge_authorized":True}
    fake=FakeDocker()
    with pytest.raises(w.WorkerHeld,match="PREFLIGHT_MISMATCH"):
        w.run("retry-backoff-code",CANDIDATE,HANDOFF,IMAGE,CONTROLLER,
           forged,root,observed_controller_sha=CONTROLLER,
           observed_candidate_sha=CANDIDATE,runner=fake)
    with pytest.raises(w.WorkerHeld,match="CANDIDATE_SHA_MISMATCH"):
        w.run("retry-backoff-code",CANDIDATE,HANDOFF,IMAGE,CONTROLLER,
           pre(),root,observed_controller_sha=CONTROLLER,
           observed_candidate_sha="f"*40,runner=fake)
    assert fake.calls==[]


def test_symlink_and_oversized_candidate_rejected(tmp_path):
    root=setup_candidate(tmp_path)
    path=root/"construct_candidates"/"retry-backoff-code.py"
    path.unlink()
    path.symlink_to(tmp_path/"secret.py")
    with pytest.raises(w.WorkerHeld,match="CANDIDATE_FILE_UNSAFE"):
        w.read_candidate(root,"retry-backoff-code")
    path.unlink()
    path.write_bytes(b"x"*8193)
    with pytest.raises(w.WorkerHeld,match="CANDIDATE_FILE_TOO_LARGE"):
        w.read_candidate(root,"retry-backoff-code")


def test_cli_preflight_no_execution_no_overwrite(tmp_path,monkeypatch):
    monkeypatch.setattr(w,"git_head",lambda path: CONTROLLER)
    out=tmp_path/"preflight.json"
    argv=["preflight","--task","retry-backoff-code",
          "--candidate-sha",CANDIDATE,"--handoff-digest",HANDOFF,
          "--image",IMAGE,"--controller-sha",CONTROLLER,
          "--controller-checkout",str(tmp_path),
          "--confirm",w.CONFIRM,"--output",str(out)]
    with contextlib.redirect_stdout(io.StringIO()):
        assert w.main(argv)==0
    assert w.load_receipt(out)["code_executed"] is False
    with contextlib.redirect_stderr(io.StringIO()):
        assert w.main(argv)==3


def test_workflow_is_manual_readonly(tmp_path):
    text=(Path(__file__).resolve().parents[2]/
          ".github/workflows/construct-r4-manual.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "\n  push:" not in text
    assert "\n  pull_request:" not in text
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "construct_training_worker.py execute" in text
