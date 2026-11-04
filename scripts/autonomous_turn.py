"""CLI for isolated worker, trusted publisher, CI observer and merge gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from autonomous_turn_contract import (REPO, REPO_ID, SCHEMA, Held, need, parse,
    validate, canonical, digest, task_digest, proposal, permit_repair)
from autonomous_turn_github import (GitHub, authority, identity, main_head,
    publish, observe, finish, return_receipt)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    need(not path.is_symlink(), "OUTPUT_SYMLINK")
    path.write_bytes(canonical(value)+b"\n")


def read(path):
    p = Path(path)
    need(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size < 300000, "INPUT_FILE")
    return parse(p.read_bytes())


def output(key, value):
    need(key.replace("_", "").isalnum() and isinstance(value, (str, int)) and
         "\n" not in str(value) and "\r" not in str(value), "OUTPUT_VALUE")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            stream.write(f"{key}={value}\n")


def bundle_digest(directory):
    return digest(canonical(read(Path(directory)/"proposal.json"))+b"\n"+
                  canonical(read(Path(directory)/"sandbox.json")))


def originals_from_checkout(task, root):
    values = {}
    root = root.resolve()
    for name in task["allowed_paths"]:
        path = root/name
        need(path.is_file() and not any(p.is_symlink() for p in [path, *path.parents]) and
             path.resolve().is_relative_to(root) and path.stat().st_size <= 100000, "CHECKOUT_PATH")
        values[name] = path.read_text(encoding="utf-8")
    return values


def worker(task, source, candidate, directory, attempt, failure=None, previous_head=None):
    # This entry point has no GitHub client and needs no token or model key.
    validate(task)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    need(actual == task["source_sha"], "CHECKOUT_SHA")
    clean = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"], text=True)
    need(clean == "", "CHECKOUT_DIRTY")
    if attempt:
        permit_repair(task, failure, previous_head, attempt)
    value = proposal(task, originals_from_checkout(task, source), attempt)
    need(not candidate.exists(), "CANDIDATE_ALREADY_EXISTS")
    shutil.copytree(source, candidate, symlinks=True, ignore=shutil.ignore_patterns(".git"))
    for change in value["changes"]:
        (candidate/change["path"]).write_bytes(change["content"].encode())
    write(directory/"proposal.json", value)
    return value


def sandbox_command(candidate, test, value):
    command = ["docker", "run", "--rm", "--network", "none", "--read-only",
        "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "128", "--memory", "2g", "--cpus", "2",
        "--tmpfs", "/tmp:rw,nosuid,size=256m,mode=1777",
        "--tmpfs", "/work:rw,exec,nosuid,size=1536m,mode=1777",
        "--mount", f"type=bind,src={candidate.resolve()},dst=/src,readonly",
        "-e", "HOME=/tmp", "-e", "CI=true"]
    if test == "docs-contract":
        expected = {c["path"]: c["after_sha256"] for c in value["changes"]}
        code = ("import sys,json,pathlib,hashlib; expected=json.loads(sys.argv[1]); "
                "assert all(hashlib.sha256((pathlib.Path('/src')/p).read_bytes()).hexdigest()==h "
                "for p,h in expected.items())")
        return command+["python:3.12-slim", "python", "-c", code, canonical(expected).decode()]
    need(test == "web-build", "TEST_COMMAND_REFUSED")
    return command+["node:22-bookworm-slim", "sh", "-euc",
                    "cp -R /src/web/. /work/ && cd /work && npm run build"]


def sandbox(task, candidate, directory, runner=subprocess.run):
    value = read(directory/"proposal.json")
    clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CI": "true"}
    results = []
    for test in task["tests"]:
        image = "python:3.12-slim" if test == "docs-contract" else "node:22-bookworm-slim"
        with tempfile.TemporaryDirectory(prefix="autonomous-npm-") as npm_home:
            env = {**clean_env, "HOME": npm_home, "NPM_CONFIG_USERCONFIG": "/dev/null"}
            if test == "web-build":
                install = runner(["npm", "ci", "--prefix", str(candidate/"web"),
                                  "--ignore-scripts", "--no-audit", "--no-fund"],
                                 env=env, timeout=300, check=False)
                need(install.returncode == 0, "DEPENDENCY_INSTALL_FAILED")
            pulled = runner(["docker", "pull", image], env=env, timeout=180, check=False)
            need(pulled.returncode == 0, "SANDBOX_IMAGE_UNAVAILABLE")
            result = runner(["timeout", "-k", "10s", "300s", *sandbox_command(candidate, test, value)],
                            env=env, timeout=320, check=False)
            results.append({"name": test, "exit_code": result.returncode})
    record = {"schema": "agentora.autonomous-sandbox.v1", "task_sha256": task_digest(task),
        "proposal_sha256": digest(canonical(value)), "attempt": value["attempt"],
        "checks": results, "isolated": True}
    write(directory/"sandbox.json", record)
    need(all(r["exit_code"] == 0 for r in results), "SANDBOX_CHECK_FAILED")
    output("bundle_sha256", bundle_digest(directory))
    return record


def example(kind, source_sha, root, now=None):
    now = now or datetime.now(timezone.utc)
    if kind == "docs":
        path = "docs/DEVELOPMENT_LOOP_R2_CODE_AND_HANDOFF.md"
        old = "The author cannot count as the independent reviewer."
        new = (old+" Review approval is bound to the current PR commit SHA; "
               "after any source push, obtain a fresh approval before applying `phi-code-automerge`.")
    else:
        path = "web/src/components/Nav.tsx"
        old = "import { Link } from 'react-router-dom'"
        new = "import { NavLink as Link } from 'react-router-dom'"
    content = (root/path).read_text()
    need(content.count(old) == 1 and new not in content, "EXAMPLE_ALREADY_APPLIED_OR_SOURCE_CHANGED")
    return {"schema": SCHEMA, "task_id": f"r1-{kind}-{now.strftime('%Y%m%d%H%M%S')}",
        "repository": REPO, "repository_id": REPO_ID, "target_branch": "main",
        "source_sha": source_sha, "created_utc": now.isoformat(),
        "expires_utc": (now+timedelta(hours=4)).isoformat(),
        "acceptance": ["Confirm the change in the deployed interface" if kind == "code" else
                       "Owner confirms the review instructions are clear"],
        "allowed_paths": [path], "max_files": 1, "max_changed_lines": 12,
        "max_patch_bytes": 4000, "tests": ["docs-contract" if kind == "docs" else "web-build"],
        "max_repairs": 0, "merge_policy": "docs" if kind == "docs" else "reviewed-code",
        "edits": [{"path": path, "before_sha256": digest(content.encode()), "old": old, "new": new}],
        "repairs": [], "human_scope": "Clarify stale review invalidation" if kind == "docs" else
        "Use React Router NavLink to expose aria-current on the active navigation link",
        "phimada_request_sha256": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "authorize", "work", "sandbox", "publish", "observe", "finish", "example"])
    parser.add_argument("--directory", type=Path, default=Path("turn-control"))
    parser.add_argument("--source", type=Path, default=Path("turn-source"))
    parser.add_argument("--candidate", type=Path, default=Path("turn-candidate"))
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--previous-head")
    parser.add_argument("--failure", type=Path)
    parser.add_argument("--kind", choices=["docs", "code"], default="docs")
    args = parser.parse_args()
    try:
        if args.stage == "example":
            sha = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
            write(args.directory/"task.json", example(args.kind, sha, args.source))
            return 0
        task = validate(parse(os.environ["TASK_JSON"]))
        directory = args.directory
        if args.stage in ("work", "sandbox"):
            if args.stage == "work":
                failure = read(args.failure) if args.failure else None
                if args.attempt:
                    need(digest(canonical(failure)) == os.environ.get("EXPECTED_OBSERVATION_SHA256"),
                         "FAILURE_ARTIFACT_DIGEST_MISMATCH")
                worker(task, args.source, args.candidate, directory, args.attempt,
                       failure, args.previous_head)
            else:
                sandbox(task, args.candidate, directory)
            return 0
        api = GitHub(os.environ["GH_TOKEN"])
        run_id, control_sha = int(os.environ["GITHUB_RUN_ID"]), os.environ["GITHUB_SHA"]
        if args.stage == "plan":
            identity(api)
            need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
            output("task_sha256", task_digest(task))
            output("source_sha", task["source_sha"])
            output("task_id", task["task_id"])
            output("task_json", canonical(task).decode())
            summary = ("### Autonomous Turn R1 — owner review required\n\nTask: `"+task["task_id"]+
                "`\n\nSource: `"+task["source_sha"]+"`\n\nPolicy: `"+task["merge_policy"]+
                "`\n\nAllowed paths: "+", ".join("`"+p+"`" for p in task["allowed_paths"])+
                "\n\nInspect the original task.json artifact. In **Review deployments**, approve "
                "`autonomous-turn-owner` with the exact comment:\n\n`APPROVE "+task_digest(task)+"`\n")
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary)
            write(directory/"task.json", task)
        elif args.stage == "authorize":
            write(directory/"authorization.json", authority(api, task, run_id, control_sha))
        else:
            expected_bundle = os.environ["EXPECTED_BUNDLE_SHA256"]
            need(bundle_digest(directory) == expected_bundle, "WORKER_BUNDLE_DIGEST_MISMATCH")
            value, isolated = read(directory/"proposal.json"), read(directory/"sandbox.json")
            need(value.get("attempt") == args.attempt, "PROPOSAL_ATTEMPT_MISMATCH")
            if args.stage == "publish":
                result = publish(api, task, value, isolated, run_id, control_sha, args.previous_head or None)
                write(directory/"published.json", result)
                output("head_sha", result["head_sha"])
                output("pr_number", result["pr_number"])
                output("published_sha256", digest(canonical(result)))
            else:
                published = read(directory/"published.json")
                need(digest(canonical(published)) == os.environ["EXPECTED_PUBLISHED_SHA256"], "PUBLISH_RECEIPT_DIGEST_MISMATCH")
                if args.stage == "observe":
                    result = observe(api, task, published, value, run_id, control_sha)
                    write(directory/"observation.json", result)
                    output("state", result["state"])
                    output("observation_sha256", digest(canonical(result)))
                else:
                    result = finish(api, task, published, value, isolated, run_id, control_sha)
                    write(directory/"turn-receipt.json", result)
                    return_receipt(api, task, result)
                    output("state", result["state"])
        return 0
    except (Held, KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, Held) else "RUNTIME_INPUT_OR_CAPABILITY_UNAVAILABLE"
        write(args.directory/"hold.json", {"schema": "agentora.autonomous-hold.v1", "state": "HELD", "reason": reason})
        print("AUTONOMOUS_TURN_HELD "+reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
