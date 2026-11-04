"""R3 local-model code proposal pilot. NEVER publishes or merges a pull request.

Only one preapproved existing low-risk React UI file may change. Ollama output
is untrusted data; real tests execute only in R1's credential-free Docker cage.
"""
from __future__ import annotations

import argparse
import difflib
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from autonomous_turn_contract import Held, canonical, digest, need, parse, HEX40, HEX64
from autonomous_turn import sandbox_command
from devloop_r2_policy import LOW_RISK_UI

SCHEMA = "agentora.r3.patch-task.v1"
RESULT = "agentora.r3.local-proposal.v1"
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}\Z")
TASK_RE = re.compile(r"[a-z][a-z0-9-]{5,63}\Z")
MAX_RESPONSE = 60000
MAX_FILE = 100000
MAX_MODEL_PORT = 65535


def task_digest(task):
    return digest((SCHEMA+"\n").encode()+canonical(task))


def load_task(path):
    need(path.is_file() and not path.is_symlink() and
         0 < path.stat().st_size <= 12000, "R3_TASK_FILE_INVALID")
    task = parse(path.read_bytes())
    need(isinstance(task, dict) and set(task) == {
        "schema", "task_id", "source_sha", "target_path",
        "before_sha256", "instruction", "acceptance",
        "max_changed_lines", "max_patch_bytes"}, "R3_TASK_FIELDS")
    need(task["schema"] == SCHEMA and
         isinstance(task["task_id"], str) and TASK_RE.fullmatch(task["task_id"]),
         "R3_TASK_ID")
    need(isinstance(task["source_sha"], str) and
         HEX40.fullmatch(task["source_sha"]), "R3_SOURCE_SHA")
    need(isinstance(task["target_path"], str) and
         task["target_path"] in LOW_RISK_UI, "R3_PATH_NOT_ALLOWLISTED")
    need(isinstance(task["before_sha256"], str) and
         HEX64.fullmatch(task["before_sha256"]), "R3_BEFORE_DIGEST")
    need(isinstance(task["instruction"], str) and
         16 <= len(task["instruction"]) <= 1200 and
         "\x00" not in task["instruction"], "R3_INSTRUCTION_INVALID")
    need(isinstance(task["acceptance"], list) and
         1 <= len(task["acceptance"]) <= 5 and
         all(isinstance(v, str) and 4 <= len(v) <= 240 and "\x00" not in v
             for v in task["acceptance"]), "R3_ACCEPTANCE_INVALID")
    need(type(task["max_changed_lines"]) is int and
         1 <= task["max_changed_lines"] <= 40 and
         type(task["max_patch_bytes"]) is int and
         64 <= task["max_patch_bytes"] <= 8000, "R3_BUDGET_INVALID")
    return task


def source_file(task, source, check=subprocess.check_output):
    need(not source.is_symlink(), "R3_SOURCE_DIRECTORY")
    source = source.resolve()
    need(source.is_dir(), "R3_SOURCE_DIRECTORY")
    # No model instruction, GitHub API request or checkout can change the source SHA.
    head = check(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    need(head == task["source_sha"], "R3_SOURCE_DRIFT")
    status = check(["git", "-C", str(source), "status", "--porcelain",
                    "--untracked-files=all"], text=True)
    need(status == "", "R3_SOURCE_DIRTY")
    file = source/task["target_path"]
    need(file.is_file() and not file.is_symlink() and
         file.resolve().is_relative_to(source) and
         all(not p.is_symlink() for p in [file, *file.parents] if p != source) and
         file.stat().st_size <= MAX_FILE, "R3_SOURCE_FILE_UNSAFE")
    raw = file.read_bytes()
    need(digest(raw) == task["before_sha256"], "R3_SOURCE_BYTES_CHANGED")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Held("R3_SOURCE_NOT_UTF8") from None
    return text


def proposal(task, before, response, model):
    need(isinstance(response, dict) and set(response) == {"content", "summary"},
         "R3_MODEL_FIELDS")
    after = response["content"]
    summary = response["summary"]
    need(isinstance(after, str) and after != before and
         0 < len(after.encode("utf-8")) <= MAX_FILE and "\x00" not in after,
         "R3_CANDIDATE_INVALID")
    need(isinstance(summary, str) and
         1 <= len(summary) <= 400 and "\x00" not in summary,
         "R3_SUMMARY_INVALID")
    patch = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="a/"+task["target_path"], tofile="b/"+task["target_path"]))
    adds = sum(line.startswith("+") and not line.startswith("+++")
               for line in patch.splitlines())
    dels = sum(line.startswith("-") and not line.startswith("---")
               for line in patch.splitlines())
    need(0 < adds+dels <= task["max_changed_lines"] and
         len(patch.encode("utf-8")) <= task["max_patch_bytes"],
         "R3_DIFF_BUDGET_EXCEEDED")
    return {"schema": RESULT, "task_sha256": task_digest(task),
            "source_sha": task["source_sha"], "target_path": task["target_path"],
            "before_sha256": task["before_sha256"],
            "after_sha256": digest(after.encode("utf-8")),
            "patch_sha256": digest(patch.encode("utf-8")),
            "patch": patch, "summary": summary, "model": model,
            "additions": adds, "deletions": dels,
            "eligible_for_merge": False, "automatic_merge": False}


def ask_ollama(task, before, model, port):
    need(isinstance(model, str) and MODEL_RE.fullmatch(model), "R3_MODEL_ID")
    need(type(port) is int and 1 <= port <= MAX_MODEL_PORT, "R3_PORT")
    system = (
        "You propose one small modification to a preselected React component. "
        "Return ONLY a JSON object with exactly two string keys: content (the "
        "entire revised UTF-8 file) and summary (under 400 chars). Keep existing "
        "routes and behavior except the requested bounded improvement. "
        "No code fences, shell commands, plugins, paths, secrets or explanations "
        "outside JSON. The proposal will be treated as untrusted data.")
    user = canonical({"source_sha": task["source_sha"],
                      "target_path": task["target_path"],
                      "instruction": task["instruction"],
                      "acceptance": task["acceptance"],
                      "before_sha256": task["before_sha256"],
                      "source": before}).decode("utf-8")
    request = canonical({"model": model, "stream": False, "format": "json",
                         "options": {"temperature": 0},
                         "messages": [{"role": "system", "content": system},
                                      {"role": "user", "content": user}]})
    # HTTPConnection does not use proxy settings or follow redirects. Nothing
    # from os.environ (including GitHub credentials) is sent to the model.
    conn = HTTPConnection("127.0.0.1", port, timeout=90)
    try:
        conn.request("POST", "/api/chat", body=request,
                     headers={"Content-Type": "application/json",
                              "Accept": "application/json"})
        reply = conn.getresponse()
        need(reply.status == 200, "R3_MODEL_HTTP_REJECTED")
        mime = reply.getheader("Content-Type", "")
        need(mime.split(";")[0].strip().lower() == "application/json",
             "R3_MODEL_MIME_REJECTED")
        raw = reply.read(MAX_RESPONSE+1)
        need(0 < len(raw) <= MAX_RESPONSE, "R3_MODEL_RESPONSE_SIZE")
        envelope = parse(raw)
        need(isinstance(envelope, dict) and
             isinstance(envelope.get("message"), dict) and
             isinstance(envelope["message"].get("content"), str),
             "R3_MODEL_ENVELOPE")
        return parse(envelope["message"]["content"])
    except (OSError, TimeoutError):
        raise Held("R3_LOCAL_MODEL_UNAVAILABLE") from None
    finally:
        conn.close()


def run_build(candidate, runner=subprocess.run):
    # Mirrors the R1 isolated UI build; no model text becomes a shell command.
    clean = {"PATH": os.environ.get("PATH", ""),
             "CI": "true", "HOME": tempfile.gettempdir(),
             "NPM_CONFIG_USERCONFIG": "NUL" if os.name == "nt" else "/dev/null"}
    install = runner(["npm", "ci", "--prefix", str(candidate/"web"),
                      "--ignore-scripts", "--no-audit", "--no-fund"],
                     env=clean, timeout=300, check=False,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    need(install.returncode == 0, "R3_DEPENDENCY_INSTALL_FAILED")
    pulled = runner(["docker", "pull", "node:22-bookworm-slim"],
                    env=clean, timeout=180, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    need(pulled.returncode == 0, "R3_SANDBOX_IMAGE_UNAVAILABLE")
    command = sandbox_command(candidate, "web-build", {"changes": []})
    result = runner(command, env=clean, timeout=330, check=False,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    need(result.returncode == 0, "R3_ISOLATED_WEB_BUILD_FAILED")
    return {"name": "web-build", "exit_code": 0,
            "network_disabled": True, "containerized": True}


def execute(task, source, model, port, build=run_build, ask=ask_ollama):
    before = source_file(task, source)
    response = ask(task, before, model, port)
    record = proposal(task, before, response, model)
    workspace = Path(tempfile.mkdtemp(prefix="agentora-r3-"))
    try:
        (workspace/"frozen-task.json").write_bytes(canonical(task)+b"\n")
        candidate = workspace/"candidate"
        shutil.copytree(source, candidate, ignore=shutil.ignore_patterns(".git"),
                        symlinks=True)
        target = candidate/task["target_path"]
        need(target.is_file() and not target.is_symlink() and
             target.resolve().is_relative_to(candidate.resolve()),
             "R3_CANDIDATE_PATH_CHANGED")
        target.write_bytes(response["content"].encode("utf-8"))
        need(digest(target.read_bytes()) == record["after_sha256"],
             "R3_CANDIDATE_BYTES_CHANGED")
        check = build(candidate)
        need(digest(target.read_bytes()) == record["after_sha256"],
             "R3_CANDIDATE_MUTATED_AFTER_TEST")
        record["checks"] = [check]
        record["state"] = "REVIEW_READY_NOT_AUTHORIZED"
        (workspace/"proposal-receipt.json").write_bytes(canonical(record)+b"\n")
        return workspace, record
    except (Held, OSError, subprocess.TimeoutExpired) as exc:
        reason = str(exc) if isinstance(exc, Held) else "R3_BUILD_OR_IO_UNAVAILABLE"
        (workspace/"hold.json").write_bytes(canonical({
            "state": "HELD", "reason": reason,
            "task_sha256": task_digest(task),
            "eligible_for_merge": False})+b"\n")
        raise
    # Disposable workspace stays local. No git push or API credentials.



def initialize(source, destination, target_path, instruction, task_id):
    """Make a fresh frozen spec; never put it inside the tracked checkout."""
    need(isinstance(target_path, str) and target_path in LOW_RISK_UI,
         "R3_INIT_PATH")
    need(isinstance(instruction, str) and 16 <= len(instruction) <= 1200,
         "R3_INIT_INSTRUCTION")
    need(isinstance(task_id, str) and TASK_RE.fullmatch(task_id),
         "R3_INIT_ID")
    need(not source.is_symlink() and source.is_dir(), "R3_SOURCE_DIRECTORY")
    root = source.resolve()
    output = destination.absolute()
    need(not output.is_relative_to(root) and
         destination.parent.is_dir() and
         not destination.is_symlink() and
         not destination.exists(), "R3_INIT_DESTINATION")
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    need(HEX40.fullmatch(head), "R3_INIT_GIT_SHA")
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        text=True)
    need(status == "", "R3_INIT_DIRTY")
    target = root/target_path
    need(target.is_file() and not target.is_symlink() and
         target.resolve().is_relative_to(root) and
         all(not p.is_symlink() for p in [target, *target.parents] if p != root)
         and target.stat().st_size <= MAX_FILE, "R3_INIT_TARGET")
    raw = target.read_bytes()
    raw.decode("utf-8", errors="strict")
    task = {"schema": SCHEMA, "task_id": task_id, "source_sha": head,
            "target_path": target_path, "before_sha256": digest(raw),
            "instruction": instruction,
            "acceptance": ["Only the authorized React component changes.",
                           "The unchanged application routes still build.",
                           "A human reviews the exact proposed diff."],
            "max_changed_lines": 24, "max_patch_bytes": 6000}
    # The whole object is frozen and reviewed in plan before any model call.
    with destination.open("xb") as stream:
        stream.write(canonical(task)+b"\n")
    return task


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("init", "plan", "run"))
    p.add_argument("spec", type=Path)
    p.add_argument("--source", type=Path, default=Path("."))
    p.add_argument("--target-path", default="web/src/components/TemplateGallery.tsx")
    p.add_argument("--task-id", default="r3-local-ui-pilot")
    p.add_argument("--instruction", default=(
        "Improve the accessibility of this component without changing "
        "external routes, dependencies or other files."))
    p.add_argument("--model", default="qwen2.5-coder:7b")
    p.add_argument("--port", type=int, default=11434)
    p.add_argument("--approve-spec-digest")
    p.add_argument("--i-approve-local-model", action="store_true")
    a = p.parse_args()
    try:
        if a.stage == "init":
            created = initialize(a.source, a.spec, a.target_path,
                                 a.instruction, a.task_id)
            print(canonical({"path": str(a.spec), "state": "FROZEN_SPEC_CREATED",
                             "frozen_spec_digest": task_digest(created)}).decode())
            return 0
        task = load_task(a.spec)
        # Plan performs NO model call, no Docker call and no writes.
        before = source_file(task, a.source)
        digest_value = task_digest(task)
        if a.stage == "plan":
            print(canonical({"task_id": task["task_id"],
                "source_sha": task["source_sha"], "path": task["target_path"],
                "before_sha256": digest(before.encode("utf-8")),
                "frozen_spec_digest": digest_value,
                "action": "REVIEW_AND_AUTHORIZE_LOCALLY"}).decode())
            return 0
        need(a.i_approve_local_model and a.approve_spec_digest == digest_value,
             "R3_EXACT_LOCAL_APPROVAL_REQUIRED")
        workspace, result = execute(task, a.source, a.model, a.port)
        print(canonical({"workspace": str(workspace), "state": result["state"],
                         "after_sha256": result["after_sha256"],
                         "eligible_for_merge": False}).decode())
        return 0
    except (Held, KeyError, ValueError, OSError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        print("R3_HELD: frozen inputs, local model or isolated build not accepted",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
