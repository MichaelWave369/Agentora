"""R3 local-model proposal safety tests; no external Ollama/Docker is called."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"scripts"))
r3 = importlib.import_module("autonomous_r3_local_patch")
c = importlib.import_module("autonomous_turn_contract")
SOURCE = "a"*40
FILE = "web/src/components/Nav.tsx"
BEFORE = ("import { NavLink as Link } from 'react-router-dom'\n"
          "export default function Nav(){return <nav/>}\n")
AFTER = ("import { NavLink as Link } from 'react-router-dom'\n"
         "export default function Nav(){return <nav aria-label=\"Main navigation\"/>}\n")


def task():
    return {"schema": r3.SCHEMA, "task_id": "r3-local-nav-a11y",
            "source_sha": SOURCE, "target_path": FILE,
            "before_sha256": c.digest(BEFORE.encode()),
            "instruction": "Improve the accessibility label of the navigation.",
            "acceptance": ["Existing navigation remains functional."],
            "max_changed_lines": 6, "max_patch_bytes": 1400}


class FakeResponse:
    def __init__(self, value, status=200, mime="application/json"):
        self.status = status
        self.mime = mime
        self.raw = json.dumps(value).encode() if isinstance(value, dict) else value

    def getheader(self, key, default=""):
        return self.mime if key.lower() == "content-type" else default

    def read(self, count):
        return self.raw[:count]


class FakeConnection:
    instances = []
    response = FakeResponse({
        "message": {"content": json.dumps({"content": AFTER, "summary": "Adds aria-label"})}})

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.args = None
        self.closed = False
        self.instances.append(self)

    def request(self, method, path, body, headers):
        self.args = (method, path, body, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class R3LocalPatchTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.instances.clear()
        FakeConnection.response = FakeResponse({
            "message": {"content": json.dumps({"content": AFTER,
                                                "summary": "Adds aria-label"})}})

    def fixture(self, root, content=BEFORE):
        path = Path(root)/FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def test_source_requires_exact_head_clean_tree_and_original_bytes(self):
        with TemporaryDirectory() as tmp:
            path = self.fixture(tmp)
            t = task()
            expected = iter([SOURCE+"\n", ""])
            self.assertEqual(r3.source_file(t, Path(tmp), check=lambda *a,**k:next(expected)), BEFORE)
            for responses in ([SOURCE+"\n", " M web/src/components/Nav.tsx\n"],
                              ["b"*40+"\n", ""]):
                with self.subTest(responses=responses), self.assertRaises(c.Held):
                    it = iter(responses)
                    r3.source_file(t, Path(tmp), check=lambda *a,**k:next(it))
            path.write_text(BEFORE+"unexpected")
            expected = iter([SOURCE+"\n", ""])
            with self.assertRaisesRegex(c.Held, "R3_SOURCE_BYTES_CHANGED"):
                r3.source_file(t, Path(tmp), check=lambda *a,**k:next(expected))

    def test_task_rejects_malicious_paths_fields_and_budgets(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"task.json"
            good=task()
            for field,value in [
                ("target_path", "../.github/workflows/ci.yml"),
                ("target_path", ["web/src/components/Nav.tsx"]),
                ("source_sha", "b"*39),
                ("max_changed_lines", 100),
                ("max_patch_bytes", True),
                ("instruction", "rm -rf /"),
                ("acceptance", []),
                ("before_sha256", "f")]:
                t=deepcopy(good);t[field]=value
                p.write_text(json.dumps(t))
                with self.subTest(field=field), self.assertRaises((c.Held,TypeError)):
                    r3.load_task(p)
            p.write_text(json.dumps(good))
            self.assertEqual(r3.load_task(p),good)
            p.write_text('{"schema": "x", "schema": "x"}')
            with self.assertRaises(c.Held): r3.load_task(p)

    def test_model_only_localhost_json_no_credentials_and_no_redirects(self):
        with patch.object(r3, "HTTPConnection", FakeConnection):
            answer = r3.ask_ollama(task(), BEFORE, "qwen2.5-coder:7b", 11434)
        self.assertEqual(answer["content"], AFTER)
        conn=FakeConnection.instances[0]
        self.assertEqual((conn.host,conn.port),("127.0.0.1",11434))
        self.assertEqual(conn.args[0:2],("POST","/api/chat"))
        self.assertTrue(conn.closed)
        self.assertNotIn("Authorization",conn.args[3])
        self.assertEqual(json.loads(conn.args[2])["stream"],False)

    def test_model_failure_is_held_not_a_patch(self):
        for response in (
            FakeResponse(b"", status=302),
            FakeResponse(b"{}", mime="text/html"),
            FakeResponse(b"x"*60001),
            FakeResponse({"message":{"content":"not-json"}}),
            FakeResponse({"message":{"content":json.dumps({"content":AFTER,"summary":"okay","command":"git push"})}})):
            FakeConnection.response = response
            with self.subTest(status=response.status),patch.object(r3,"HTTPConnection",FakeConnection):
                with self.assertRaises(c.Held):
                    response_data=r3.ask_ollama(task(),BEFORE,"qwen2.5-coder:7b",11434)
                    r3.proposal(task(), BEFORE, response_data, "qwen2.5-coder:7b")
        for model in ("", "../evil", "qwen bad", "☠"):
            with self.subTest(model=model), self.assertRaises(c.Held):
                r3.ask_ollama(task(), BEFORE, model, 11434)

    def test_proposal_exact_one_file_small_diff_and_never_merge_authorizes(self):
        t=task()
        p=r3.proposal(t,BEFORE,{"content":AFTER,"summary":"Adds aria-label"},"qwen2.5-coder:7b")
        self.assertEqual(p["target_path"],FILE)
        self.assertEqual(p["after_sha256"],c.digest(AFTER.encode()))
        self.assertFalse(p["automatic_merge"])
        self.assertFalse(p["eligible_for_merge"])
        self.assertLessEqual(p["additions"]+p["deletions"],6)
        with self.assertRaisesRegex(c.Held,"R3_DIFF_BUDGET_EXCEEDED"):
            r3.proposal(t, BEFORE, {"content":"\n".join(f"line {i}" for i in range(100)),
                                      "summary":"Too large"},"qwen2.5-coder:7b")
        for bad in ({"content": BEFORE,"summary":"unchanged"},
                    {"content": AFTER,"summary":""},
                    {"content": AFTER,"summary":"x","token":"secret"},
                    {"content": AFTER+"\x00","summary":"bad"}):
            with self.subTest(bad=bad),self.assertRaises(c.Held):
                r3.proposal(t, BEFORE, bad, "qwen2.5-coder:7b")

    def test_build_invokes_fixed_networkless_nonroot_container_not_model_shell(self):
        commands=[]
        def fake_runner(args,**kwargs):
            commands.append((args,kwargs))
            return SimpleNamespace(returncode=0)
        with TemporaryDirectory() as tmp:
            self.fixture(tmp)
            result=r3.run_build(Path(tmp),runner=fake_runner)
        self.assertEqual(result["name"],"web-build")
        self.assertEqual(len(commands),3)
        self.assertIn("--ignore-scripts",commands[0][0])
        cmd=commands[2][0]
        for item in ("docker","run","--network","none","--read-only","--cap-drop",
                     "ALL","--pids-limit","--security-opt","no-new-privileges"):
            self.assertIn(item,cmd)
        self.assertNotIn("GH_TOKEN",commands[2][1]["env"])
        self.assertNotIn("AUTONOMOUS_PUBLISH_APP_KEY",commands[2][1]["env"])
        self.assertIn("readonly",next(v for v in cmd if "dst=/src" in v))

    def test_end_to_end_fake_model_keeps_workspace_nonpublishing(self):
        with TemporaryDirectory() as tmp:
            self.fixture(tmp)
            fake = lambda t,b,m,p: {"content":AFTER,"summary":"Adds aria-label"}
            test = lambda path: {"name":"web-build","exit_code":0,
                                 "network_disabled":True,"containerized":True}
            with patch.object(r3,"source_file",return_value=BEFORE):
                workspace,receipt=r3.execute(task(),Path(tmp),"test-model",11434,
                                             build=test,ask=fake)
            try:
                self.assertEqual(receipt["state"],"REVIEW_READY_NOT_AUTHORIZED")
                self.assertFalse(receipt["eligible_for_merge"])
                self.assertEqual((workspace/"candidate"/FILE).read_text(),AFTER)
                self.assertEqual((Path(tmp)/FILE).read_text(),BEFORE)
                self.assertEqual(json.loads((workspace/"proposal-receipt.json").read_text())["after_sha256"],
                                 c.digest(AFTER.encode()))
            finally:
                shutil.rmtree(workspace)

    def test_no_authorization_refuses_before_model_dispatch(self):
        with TemporaryDirectory() as tmp:
            spec=Path(tmp)/"task.json"
            spec.write_text(json.dumps(task()))
            for args in (["run",str(spec)], ["run",str(spec),"--i-approve-local-model",
                                           "--approve-spec-digest","f"*64]):
                with patch.object(sys,"argv",["r3",*args]), patch.object(r3,"source_file",return_value=BEFORE), patch.object(r3,"execute") as execute:
                    self.assertEqual(r3.main(),1)
                    execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
