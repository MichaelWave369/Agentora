"""Adversarial R15 tests. No network or actual GitHub mutation."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
import devloop_r15_smerge_batch as s

HEAD="a"*40
BASE="b"*40


def owner_event(mode="preview", raw="31@"+HEAD, confirmation=""):
    return {"sender":{"login":s.OWNER,"id":s.OWNER_ID},
      "repository":{"full_name":s.REPO,"id":s.REPO_ID},
      "inputs":{"mode":mode,"pr_heads":raw,"confirmation":confirmation}}


def environment():
    return {"GITHUB_EVENT_NAME":"workflow_dispatch","GITHUB_REPOSITORY":s.REPO,
        "GITHUB_REPOSITORY_ID":str(s.REPO_ID),"GITHUB_REF":"refs/heads/main",
        "GITHUB_ACTOR":s.OWNER,"GITHUB_ACTOR_ID":str(s.OWNER_ID),
        "GITHUB_RUN_ATTEMPT":"1"}


def pr(filename="docs/README.md", sha=HEAD):
    return {"number":31,"state":"open","draft":False,
        "base":{"ref":"main","sha":BASE,"repo":{"full_name":s.REPO}},
        "head":{"sha":sha,"repo":{"full_name":s.REPO}},
        "user":{"login":s.OWNER,"id":s.OWNER_ID},"labels":[],
        "changed_files":1,"mergeable":True}


def docs_file(filename="docs/test.md"):
    return {"filename":filename,"status":"modified","additions":1,"deletions":1,
            "sha":"c"*40,"changes":2}


class SmergeR15(unittest.TestCase):
    def test_strict_exact_sha_list(self):
        self.assertEqual(s.parse_heads("31@"+HEAD+", 32@"+"d"*40),
                         [(31,HEAD),(32,"d"*40)])
        for raw in ("","31@main","31@"+"A"*40,"0@"+HEAD,
                    "31@"+HEAD+",31@"+HEAD,
                    "31@"+HEAD+",", "31@"+HEAD*14,
                    ",".join(f"{i+1}@{HEAD}" for i in range(6)),
                    "31@"+HEAD+"; rm -rf /"):
            with self.subTest(raw=raw[:45]),self.assertRaises(s.Hold):
                s.parse_heads(raw)

    def test_owner_and_event_origin_required(self):
        env=environment()
        event=owner_event("merge",confirmation=s.CONFIRM)
        self.assertEqual(s.check_dispatch(env,event),("merge",[(31,HEAD)]))
        for key,value in (("GITHUB_EVENT_NAME","pull_request"),
                          ("GITHUB_REF","refs/heads/dev"),
                          ("GITHUB_ACTOR","someone"),
                          ("GITHUB_ACTOR_ID","100"),
                          ("GITHUB_REPOSITORY","MichaelWave369/Other"),
                          ("GITHUB_REPOSITORY_ID","1"),
                          ("GITHUB_RUN_ATTEMPT","2")):
            wrong=env.copy();wrong[key]=value
            with self.subTest(key=key),self.assertRaises(s.Hold):
                s.check_dispatch(wrong,event)
        bad=owner_event("merge",confirmation="NOT_APPROVED")
        with self.assertRaises(s.Hold): s.check_dispatch(env,bad)
        bad=owner_event("merge",confirmation=s.CONFIRM);bad["sender"]["id"]=1
        with self.assertRaises(s.Hold): s.check_dispatch(env,bad)
        bad=owner_event();bad["repository"]["id"]=3
        with self.assertRaises(s.Hold): s.check_dispatch(env,bad)

    def test_doc_only_source_author_and_holds(self):
        files=[docs_file()]
        self.assertEqual(s.docs_snapshot(pr(),31,HEAD,files)["head_sha"],HEAD)
        for path in (".github/workflows/ci.yml","scripts/devloop_automerge.py",
                     "web/src/main.tsx","docs/../README.md","docs/payload.js",
                     "docs/../../secret.md"):
            with self.subTest(path=path),self.assertRaises(s.Hold):
                s.docs_snapshot(pr(),31,HEAD,[docs_file(path)])
        changes=[
           ("draft",True),("mergeable",None),("changed_files",2),
           ("state","closed")]
        for key,value in changes:
            candidate=pr();candidate[key]=value
            with self.subTest(key=key),self.assertRaises(s.Hold):
                s.docs_snapshot(candidate,31,HEAD,files)
        bad=pr();bad["user"]["id"]=1
        with self.assertRaises(s.Hold): s.docs_snapshot(bad,31,HEAD,files)
        for label in ("security-review","hold","phi-code-automerge",
                      "phi-solo-automerge","phi-automerge"):
            bad=pr();bad["labels"]=[{"name":label}]
            with self.subTest(label=label),self.assertRaises(s.Hold):
                s.docs_snapshot(bad,31,HEAD,files)

    def test_fingerprint_detects_content_metadata_drift(self):
        f=docs_file()
        changed=dict(f);changed["sha"]="d"*40
        self.assertNotEqual(s.file_fingerprint([f]),s.file_fingerprint([changed]))

    def test_incomplete_pr_files_refused(self):
        with patch.object(s,"api",return_value=[]):
            with self.assertRaises(s.Hold):s.fetch_files("token",31,1)

    def test_all_checks_must_be_green_including_unrequired(self):
        check={"total_count":4,"check_runs":[
            {"status":"completed","conclusion":"success"} for _ in range(4)]}
        status={"statuses":[{"state":"success"}]}
        with patch.object(s,"api",side_effect=[check,status]),\
             patch.object(s.guard,"require_required_checks_green") as required:
            s.all_checks_green("token",HEAD)
            required.assert_called_once_with("token",HEAD)
        for state in ("failure","cancelled","skipped",None):
            bad={"total_count":1,"check_runs":[
                {"status":"completed","conclusion":state}]}
            with patch.object(s,"api",return_value=bad),self.assertRaises(s.Hold):
                s.all_checks_green("token",HEAD)
        with patch.object(s,"api",return_value={"total_count":100,"check_runs":[]}),\
             self.assertRaises(s.Hold):
            s.all_checks_green("token",HEAD)

    def test_preview_never_merges_and_held_candidate_blocks_all(self):
        rows=[(31,HEAD),(32,"d"*40)]
        counter={"write":0}
        def reader(_token,n,sha):
            if n==32: raise s.Hold("CI_PENDING")
            return {"number":n,"head_sha":sha,"base_sha":BASE}
        def fetch(*args):
            counter["write"]+=1
        report=s.run_batch("token","merge",rows,reader,fetch)
        self.assertEqual([d["state"] for d in report],
                         ["READY_FOR_OWNER_DISPATCH","HELD"])
        self.assertEqual(counter["write"],0)
        report=s.run_batch("token","preview",[(31,HEAD)],reader,fetch)
        self.assertEqual(report[0]["state"],"READY_FOR_OWNER_DISPATCH")
        self.assertEqual(counter["write"],0)

    def test_merged_requires_fresh_authority_and_real_readback(self):
        rows=[(31,HEAD)]
        calls={"inspect":0,"writes":0}
        def reader(_token,n,sha):
            calls["inspect"]+=1
            return {"number":n,"head_sha":sha,"base_sha":BASE,"files_sha256":"a"*64}
        def fetch(_token,path,payload=None,method=None):
            if method=="PUT":
                calls["writes"]+=1
                self.assertEqual(payload,{"sha":HEAD,"merge_method":"squash"})
                return {"merged":True}
            return {"merged":True,"merge_commit_sha":"e"*40}
        report=s.run_batch("token","merge",rows,reader,fetch)
        self.assertEqual(report[0]["state"],"MERGED_GITHUB_READBACK")
        self.assertEqual(calls,{"inspect":2,"writes":1})
        def fail_readback(*args):
            if len(args)>2:return {"merged":True}
            return {"merged":False}
        report=s.run_batch("token","merge",rows,reader,fail_readback)
        self.assertEqual(report[0]["state"],"HELD_AFTER_WRITE_ATTEMPT")

    def test_changed_source_holds_before_mutation(self):
        seen={"n":0}
        def reader(_token,n,sha):
            seen["n"]+=1
            return {"head_sha":sha,"base_sha":BASE if seen["n"]==1 else "f"*40}
        report=s.run_batch("token","merge",[(31,HEAD)],reader,lambda *a: self.fail("write"))
        self.assertEqual(report[0]["state"],"HELD_AFTER_WRITE_ATTEMPT")

    def test_no_automatic_trigger_in_workflow(self):
        path=Path(__file__).resolve().parents[2]/".github/workflows/devloop-r15-smerge-batch.yml"
        content=path.read_text(encoding="utf8")
        self.assertIn("workflow_dispatch:",content)
        self.assertNotIn("pull_request_target:",content)
        self.assertNotIn("schedule:",content)
        self.assertNotIn("issues:",content)
        self.assertIn("contents: write",content)
        self.assertIn("contents: read",content)
        self.assertIn("GITHUB_ACTOR_ID:",content)
        self.assertIn("ref: main",content)
        self.assertIn("if: always()",content)


if __name__=="__main__":
    unittest.main()
