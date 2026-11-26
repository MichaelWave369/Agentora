"""R05-A: review and test one bounded replacement using a prewarmed offline cage."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import autonomous_r3_local_patch as r3
from autonomous_turn_contract import Held, canonical, digest, need

IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
BUILD = ("mkdir /work/web /work/cache && cp -R /src/web/. /work/web/ && "
         "cp -R /cache/. /work/cache/ && cd /work/web && "
         "npm ci --offline --ignore-scripts --no-audit --no-fund "
         "--cache /work/cache --userconfig /dev/null --globalconfig /dev/null && "
         "npm run build")
SCHEMA = "agentora.phiforge.r05a.v1"


def safe_directory(path):
    path = Path(path)
    need(path.is_dir() and not path.is_symlink(), "FORGE_DIRECTORY")
    resolved = path.resolve()
    need(not any(c in str(resolved) for c in (",", "\n", "\r")),
         "FORGE_MOUNT_PATH")
    return resolved


def read_replacement(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink(), "FORGE_REPLACEMENT")
    with path.open("rb") as stream:
        raw = stream.read(r3.MAX_FILE + 1)
    need(0 < len(raw) <= r3.MAX_FILE, "FORGE_REPLACEMENT_SIZE")
    return raw.decode("utf-8", errors="strict")


def prepare(task, source, replacement, image, cache):
    need(isinstance(image, str) and IMAGE.fullmatch(image), "FORGE_IMAGE_ID")
    source = safe_directory(source)
    cache = safe_directory(cache)
    need(not cache.is_relative_to(source) and not source.is_relative_to(cache),
         "FORGE_CACHE_MUST_BE_SEPARATE")
    before = r3.source_file(task, source)
    blob = subprocess.check_output(
        ["git", "-C", str(source), "show", task["source_sha"] + ":" + task["target_path"]],
        timeout=30)
    need(blob == before.encode("utf-8"), "FORGE_CHECKOUT_BLOB_MISMATCH")
    after = read_replacement(replacement)
    record = r3.proposal(task, before, {"content": after, "summary": "Operator-supplied replacement"},
                         "operator-supplied")
    plan = {"schema": SCHEMA, "state": "REVIEW_REQUIRED",
            "task": task, "proposal": record, "image_id": image,
            "cache_directory": str(cache), "source_directory": str(source),
            "build_recipe_sha256": digest(BUILD.encode("utf-8")),
            "eligible_for_merge": False, "offline_verified": False}
    return plan, after


def plan_digest(plan):
    return digest(canonical(plan))


def docker_command(candidate, cache, image):
    candidate = safe_directory(candidate)
    cache = safe_directory(cache)
    need(isinstance(image, str) and IMAGE.fullmatch(image), "FORGE_IMAGE_ID")
    # Explicit local daemon transport, no DOCKER_HOST or current-context selection.
    host = "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
    return ["docker", "--host", host, "run", "--rm", "--pull=never",
            "--network", "none", "--read-only", "--user", "65534:65534",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "128", "--memory", "3g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,nosuid,size=256m,mode=1777",
            "--tmpfs", "/work:rw,exec,nosuid,size=2048m,mode=1777",
            "--mount", f"type=bind,src={candidate},dst=/src,readonly",
            "--mount", f"type=bind,src={cache},dst=/cache,readonly",
            "-e", "HOME=/tmp", "-e", "CI=true", "--entrypoint", "/bin/sh",
            image, "-euc", BUILD]


def run_approved(task, source, replacement, image, cache, approved, offline,
                 runner=subprocess.run):
    need(offline is True, "FORGE_OFFLINE_CONFIRMATION_REQUIRED")
    plan, after = prepare(task, source, replacement, image, cache)
    need(approved == plan_digest(plan), "FORGE_EXACT_APPROVAL_REQUIRED")
    source = Path(plan["source_directory"])
    cache = Path(plan["cache_directory"])
    with tempfile.TemporaryDirectory(prefix="phiforge-r05a-") as temp:
        root = Path(temp)
        candidate = root / "candidate"
        r3.tracked_source(source, task["source_sha"], candidate)
        target = candidate / task["target_path"]
        need(target.is_file() and not target.is_symlink()
             and target.resolve().is_relative_to(candidate.resolve())
             and digest(target.read_bytes()) == task["before_sha256"],
             "FORGE_ARCHIVE_TARGET_MISMATCH")
        target.write_bytes(after.encode("utf-8"))
        need(digest(target.read_bytes()) == plan["proposal"]["after_sha256"],
             "FORGE_CANDIDATE_CHANGED")
        # Recheck approval against the live clean checkout and selected inputs.
        current, _ = prepare(task, source, replacement, image, cache)
        need(plan_digest(current) == approved, "FORGE_INPUT_DRIFT")
        docker_config = root / "docker-config"
        docker_config.mkdir()
        clean = {"PATH": os.environ.get("PATH", ""), "DOCKER_CONFIG": str(docker_config)}
        # Windows Docker client may need OS runtime paths, not user secrets.
        if os.name == "nt":
            for name in ("SystemRoot", "WINDIR", "TEMP", "TMP"):
                if name in os.environ:
                    clean[name] = os.environ[name]
        result = runner(docker_command(candidate, cache, image),
                        env=clean, timeout=330, check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        need(digest(target.read_bytes()) == plan["proposal"]["after_sha256"],
             "FORGE_CANDIDATE_CHANGED_AFTER_TEST")
        return {"schema": SCHEMA, "state": "BUILD_PASS_REVIEW_ONLY" if result.returncode == 0 else "HELD",
                "exit_code": result.returncode, "plan_sha256": approved,
                "source_sha": task["source_sha"], "patch_sha256": plan["proposal"]["patch_sha256"],
                "after_sha256": plan["proposal"]["after_sha256"], "image_id": image,
                "operator_declared_offline": True, "offline_verified": False,
                "network_none_requested": True, "pull_never_requested": True,
                "eligible_for_merge": False, "execution_authority": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "test"))
    parser.add_argument("spec", type=Path)
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--replacement", type=Path, required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--approve-digest")
    parser.add_argument("--confirm-offline", action="store_true")
    args = parser.parse_args(argv)
    try:
        task = r3.load_task(args.spec)
        if args.stage == "plan":
            plan, _ = prepare(task, args.source, args.replacement, args.image_id, args.cache)
            result = {"plan": plan, "plan_sha256": plan_digest(plan)}
        else:
            result = run_approved(task, args.source, args.replacement, args.image_id,
                                  args.cache, args.approve_digest, args.confirm_offline)
        print(canonical(result).decode("utf-8"))
        return 1 if result.get("state") == "HELD" else 0
    except (Held, ValueError, TypeError, OSError, subprocess.SubprocessError):
        print("FORGE_HELD: inputs, approval or isolated build unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
