"""PhiConstruct R4: opt-in, bounded GitHub Actions training diagnostic.

Only a fixed small Python source file is executed in restricted containers,
never directly on the host. A result cannot authorize another agent action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

SCHEMA_PRE = "agentora.construct.r4-preflight.v0.4"
SCHEMA_RESULT = "agentora.construct.r4-result.v0.4"
CONFIRM = "RUN_BOUNDED_CONSTRUCT_TRAINING"
TASKS = frozenset({"retry-backoff-code", "repo-slug-code"})
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
HASH = re.compile(r"sha256:[a-f0-9]{64}\Z")
IMAGE = re.compile(r"python:3\.12-alpine@sha256:[a-f0-9]{64}\Z")
FIXTURES = Path(__file__).resolve().parent.parent / "construct_tasks"
MAX_CODE = 8192
TIMEOUT = 8


class WorkerHeld(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise WorkerHeld(reason)


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def task_for(identifier):
    require(type(identifier) is str and identifier in TASKS, "TASK_NOT_ALLOWLISTED")
    path = FIXTURES / (identifier + ".json")
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= 24576, "TASK_FILE_UNSAFE")
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise WorkerHeld("TASK_INVALID_JSON") from exc
    require(type(task) is dict and set(task) == {
        "schema_version", "id", "version", "title", "pack_id",
        "instructions", "function", "signature", "cases"
    } and task["schema_version"] == 1 and task["id"] == identifier
            and task["version"] == "0.1.0"
            and task["pack_id"] == "core.repo-evidence"
            and task["function"] == {
                "retry-backoff-code": "retry_delay",
                "repo-slug-code": "normalize_slug",
            }[identifier], "TASK_CONTRACT_INVALID")
    require(type(task["cases"]) is list and len(task["cases"]) == 7,
            "TASK_CHECKS_INVALID")
    for case in task["cases"]:
        require(type(case) is dict and set(case) == {"args", "expected"}
                and type(case["args"]) is list and len(case["args"]) == 1
                and type(case["args"][0]) in (int, str)
                and type(case["expected"]) in (int, str),
                "TASK_CASE_INVALID")
    return task


def prepare(task_id, candidate_sha, handoff_digest, image, controller_sha, confirmation):
    require(confirmation == CONFIRM, "MANUAL_CONFIRMATION_REQUIRED")
    require(type(candidate_sha) is str and SHA40.fullmatch(candidate_sha),
            "CANDIDATE_SHA_INVALID")
    require(type(controller_sha) is str and SHA40.fullmatch(controller_sha),
            "CONTROLLER_SHA_INVALID")
    require(type(handoff_digest) is str and HASH.fullmatch(handoff_digest),
            "HANDOFF_DIGEST_INVALID")
    require(type(image) is str and IMAGE.fullmatch(image),
            "IMAGE_NOT_PINNED_OR_DISALLOWED")
    task = task_for(task_id)
    return {
        "schema": SCHEMA_PRE,
        "state": "MANUAL_PREFLIGHT_ONLY",
        "task_id": task_id,
        "task_digest": digest(encode(task)),
        "task_version": task["version"],
        "pack_id": task["pack_id"],
        "pack_approval_verified": False,
        "handoff_digest_claim": handoff_digest,
        "candidate_repository": "MichaelWave369/Agentora",
        "candidate_sha": candidate_sha,
        "controller_sha": controller_sha,
        "candidate_file": "construct_candidates/" + task_id + ".py",
        "image": image,
        "manual_confirmation": True,
        "code_executed": False,
        "agent_identity_authenticated": False,
        "lease_attested": False,
        "merge_authorized": False,
        "dispatch_authorized": False,
        "deployment_authorized": False,
    }


def git_head(checkout):
    path = Path(checkout)
    require(path.is_dir() and not path.is_symlink(), "CHECKOUT_UNSAFE")
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        raise WorkerHeld("GIT_HEAD_UNAVAILABLE") from exc
    sha = result.stdout.strip()
    require(SHA40.fullmatch(sha), "GIT_HEAD_INVALID")
    return sha


def read_candidate(checkout, task_id):
    root = Path(checkout)
    folder = root / "construct_candidates"
    file = folder / (task_id + ".py")
    require(root.is_dir() and not root.is_symlink()
            and folder.is_dir() and not folder.is_symlink()
            and file.is_file() and not file.is_symlink()
            and file.resolve().is_relative_to(root.resolve()),
            "CANDIDATE_FILE_UNSAFE")
    require(0 < file.stat().st_size <= 8192, "CANDIDATE_FILE_TOO_LARGE")
    try:
        value = file.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise WorkerHeld("CANDIDATE_UTF8_REQUIRED") from exc
    require("\x00" not in value, "CANDIDATE_NUL_INVALID")
    return value


# Trusted host-side grading compares a value to expected fixed task output.
# The candidate Python executes inside a container only. The wrapper is
# part of the diagnostic, not adversarially secure attribution.
WRAPPER = r'''import contextlib
import importlib.util
import io
import json

try:
    with open("/task/input.json", encoding="utf-8") as f:
        payload = json.load(f)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec = importlib.util.spec_from_file_location("candidate", "/task/candidate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = getattr(module, payload["function"])(*payload["args"])
    print("__PHI_R4__" + json.dumps({"value": result}, allow_nan=False,
          ensure_ascii=False, separators=(",", ":")), flush=True)
except BaseException:
    print("__PHI_R4_ERROR__", flush=True)
'''


def docker_argv(image, directory, cid):
    return [
        "docker", "run", "--rm", "--pull=never", "--network=none",
        "--read-only", "--ipc=none", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=32",
        "--memory=128m", "--memory-swap=128m", "--cpus=0.50",
        "--ulimit=nofile=64:64", "--user=65534:65534",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=PYTHONNOUSERSITE=1", "--workdir=/task",
        "--mount=type=bind,src=" + str(directory) + ",dst=/task,readonly",
        "--cidfile=" + str(cid), "--entrypoint=python3",
        image, "-I", "-B", "-S", "/task/wrapper.py",
    ]


def limit_output():
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, 65536))


def cleanup(cid):
    path = Path(cid)
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 128:
            return
        value = path.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-f0-9]{12,64}", value):
            return
        subprocess.run(["docker", "rm", "-f", value],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=False)
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        pass


def evaluate(image, code, function, args, expected, *, runner=subprocess.run):
    with tempfile.TemporaryDirectory(prefix="construct-r4-") as tmp:
        directory = Path(tmp)
        directory.chmod(0o755)
        for name, content in (
            ("candidate.py", code),
            ("wrapper.py", WRAPPER),
            ("input.json", json.dumps({"function": function, "args": args})),
        ):
            file = directory / name
            file.write_text(content, encoding="utf-8")
            file.chmod(0o644)
        cid = directory / "cid"
        with tempfile.TemporaryFile(mode="w+b") as out, \
             tempfile.TemporaryFile(mode="w+b") as err:
            try:
                result = runner(docker_argv(image, directory, cid),
                                stdout=out, stderr=err, timeout=TIMEOUT,
                                check=False, preexec_fn=limit_output)
            except (OSError, subprocess.TimeoutExpired) as exc:
                cleanup(cid)
                raise WorkerHeld("CONTAINER_RUN_UNAVAILABLE_OR_TIMED_OUT") from exc
            out.seek(0)
            raw = out.read(8193)
            if result.returncode != 0 or len(raw) > 8192:
                return False
            try:
                lines = raw.decode("utf-8").splitlines()
                if len(lines) != 1 or not lines[0].startswith("__PHI_R4__"):
                    return False
                value = json.loads(lines[0][len("__PHI_R4__"):])
                return (type(value) is dict and set(value) == {"value"}
                        and type(value["value"]) is type(expected)
                        and value["value"] == expected)
            except (UnicodeError, ValueError):
                return False


def run(task_id, candidate_sha, handoff_digest, image, controller_sha,
        preflight, checkout, *, observed_controller_sha, observed_candidate_sha,
        runner=subprocess.run):
    expected = prepare(task_id, candidate_sha, handoff_digest,
                       image, controller_sha, CONFIRM)
    require(preflight == expected, "PREFLIGHT_MISMATCH")
    require(observed_controller_sha == controller_sha, "CONTROLLER_SHA_MISMATCH")
    require(observed_candidate_sha == candidate_sha, "CANDIDATE_SHA_MISMATCH")
    task = task_for(task_id)
    code = read_candidate(checkout, task_id)
    results = [
        evaluate(image, code, task["function"], case["args"],
                 case["expected"], runner=runner)
        for case in task["cases"]
    ]
    passed = all(results)
    return {
        "schema": SCHEMA_RESULT,
        "state": ("BOUNDED_CHECKS_PASSED" if passed else "BOUNDED_CHECKS_FAILED"),
        "task_id": task_id,
        "task_version": task["version"],
        "task_digest": expected["task_digest"],
        "pack_id": expected["pack_id"],
        "pack_approval_independently_verified": False,
        "handoff_digest_claim": handoff_digest,
        "candidate_repository": expected["candidate_repository"],
        "candidate_sha": candidate_sha,
        "candidate_file": expected["candidate_file"],
        "candidate_file_digest": digest(code.encode("utf-8")),
        "controller_sha": controller_sha,
        "image": image,
        "checks": results,
        "passed_count": sum(results),
        "total_cases": len(results),
        "container_invocations": len(results),
        "untrusted_candidate_executed_in_container": True,
        "github_artifact_digest_independently_verified": False,
        "remote_worker_lease_attested": False,
        "agent_identity_authenticated": False,
        "general_competence_verified": False,
        "execution_authorized_after_training": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "manual_review_required": True,
    }


def load_receipt(path):
    file = Path(path)
    require(file.is_file() and not file.is_symlink()
            and 0 < file.stat().st_size <= 16384, "RECEIPT_FILE_UNSAFE")
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise WorkerHeld("RECEIPT_JSON_INVALID") from exc
    require(type(value) is dict, "RECEIPT_INVALID")
    return value


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    require(len(payload.encode("utf-8")) <= 16384, "OUTPUT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="phase", required=True)
    for name in ("preflight", "execute"):
        p = subs.add_parser(name)
        p.add_argument("--task", required=True, choices=sorted(TASKS))
        p.add_argument("--candidate-sha", required=True)
        p.add_argument("--handoff-digest", required=True)
        p.add_argument("--image", required=True)
        p.add_argument("--controller-sha", required=True)
        p.add_argument("--controller-checkout", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        if name == "preflight":
            p.add_argument("--confirm", required=True)
        else:
            p.add_argument("--candidate-checkout", type=Path, required=True)
            p.add_argument("--preflight", type=Path, required=True)
    a = parser.parse_args(argv)
    try:
        controller_head = git_head(a.controller_checkout)
        if a.phase == "preflight":
            require(controller_head == a.controller_sha, "CONTROLLER_SHA_MISMATCH")
            result = prepare(a.task, a.candidate_sha, a.handoff_digest,
                             a.image, a.controller_sha, a.confirm)
        else:
            result = run(
                a.task, a.candidate_sha, a.handoff_digest, a.image,
                a.controller_sha, load_receipt(a.preflight),
                a.candidate_checkout, observed_controller_sha=controller_head,
                observed_candidate_sha=git_head(a.candidate_checkout),
            )
        write_new(a.output, result)
        print(json.dumps({"state": result["state"], "merge_authorized": False}))
        return 0
    except (WorkerHeld, OSError, ValueError) as exc:
        print("CONSTRUCT_R4_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
