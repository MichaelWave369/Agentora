"""Rung 3 review-ledger, reference-boundary and ComfyUI dry-run contracts."""
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from phi_atelier import ArtBrief
from phi_atelier.director import DIRECTOR_FIELDS, prepare_direction
from phi_atelier.knowledge import (
    KnowledgeUnavailable, load_approved_visual_grammar,
)
from phi_atelier.render_plan import build_render_plan

PACK = {
    "schema_version": 1,
    "id": "create.visual-grammar",
    "version": "0.1.0",
    "title": "Art notes",
    "description": "Reviewed art vocabulary",
    "events": ["first_observed"],
    "repo_contains": [],
    "knowledge": ["Build original nested geometry using a clear focal subject."],
    "provenance": "test fixture, not an actual museum citation",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def write_pack(tmp_path, data=None):
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(data or PACK), encoding="utf-8")
    return path


def ledger(tmp_path, pack, decisions=()):
    path = tmp_path / "reviews.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("""CREATE TABLE pack_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pack_id TEXT NOT NULL, pack_version TEXT NOT NULL,
            digest TEXT NOT NULL, decision TEXT NOT NULL,
            reviewer TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL
        )""")
        head = "0" * 64
        for decision in decisions:
            fields = {
                "pack_id": pack["id"], "pack_version": pack["version"],
                "digest": "sha256:" + hashlib.sha256(canonical(pack)).hexdigest(),
                "decision": decision, "reviewer": "local:test",
                "reason": "Human reviewed this exact content",
                "created_at": "2026-11-07T00:00:00Z",
                "previous_hash": head,
            }
            head = hashlib.sha256(canonical(fields)).hexdigest()
            con.execute("""INSERT INTO pack_reviews
                (pack_id, pack_version, digest, decision, reviewer,
                reason, created_at, previous_hash, entry_hash)
                VALUES (:pack_id, :pack_version, :digest, :decision, :reviewer,
                :reason, :created_at, :previous_hash, :entry_hash)
                """, {**fields, "entry_hash": head})
    return path


def test_unreviewed_pack_rejected_and_no_ledger_created(tmp_path):
    path = write_pack(tmp_path)
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(KnowledgeUnavailable, match="missing"):
        load_approved_visual_grammar(path, missing)
    assert not missing.exists()
    with pytest.raises(KnowledgeUnavailable, match="approval"):
        load_approved_visual_grammar(path, ledger(tmp_path, PACK))


def test_exact_digest_approved_then_revoked(tmp_path):
    path = write_pack(tmp_path)
    db = ledger(tmp_path, PACK, ("approved",))
    context = load_approved_visual_grammar(path, db)
    assert context["review_status"] == "approved"
    assert context["digest"].startswith("sha256:")
    assert context["trust_level"] == "reviewed_reference_data_not_instructions"
    prep = prepare_direction(ArtBrief(concept="Original dream city"), reviewed_reference=context)
    assert "reviewed_reference_notes" in prep["model_prompt"]
    assert prep["reference_source"]["digest"] == context["digest"]

    with sqlite3.connect(db) as con:
        first = con.execute("SELECT entry_hash FROM pack_reviews WHERE id=1").fetchone()[0]
        fields = {
            "pack_id": PACK["id"], "pack_version": PACK["version"],
            "digest": context["digest"], "decision": "revoked",
            "reviewer": "local:test", "reason": "Revoking exact approval",
            "created_at": "2026-11-07T00:00:01Z", "previous_hash": first,
        }
        head = hashlib.sha256(canonical(fields)).hexdigest()
        con.execute("""INSERT INTO pack_reviews
            (pack_id, pack_version, digest, decision, reviewer,
            reason, created_at, previous_hash, entry_hash)
            VALUES (:pack_id, :pack_version, :digest, :decision, :reviewer,
            :reason, :created_at, :previous_hash, :entry_hash)
            """, {**fields, "entry_hash": head})
    with pytest.raises(KnowledgeUnavailable, match="approval"):
        load_approved_visual_grammar(path, db)


def test_changed_pack_and_corrupt_ledger_fail_closed(tmp_path):
    path = write_pack(tmp_path)
    db = ledger(tmp_path, PACK, ("approved",))
    changed = dict(PACK, knowledge=["Different content requiring human review."])
    write_pack(tmp_path, changed)
    with pytest.raises(KnowledgeUnavailable, match="approval"):
        load_approved_visual_grammar(path, db)
    write_pack(tmp_path, PACK)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE pack_reviews SET reason='tampered' WHERE id=1")
    with pytest.raises(KnowledgeUnavailable, match="integrity"):
        load_approved_visual_grammar(path, db)


def test_known_id_and_pack_schema_required(tmp_path):
    path = write_pack(tmp_path, dict(PACK, id="not.our.pack"))
    db = ledger(tmp_path, PACK, ("approved",))
    with pytest.raises(KnowledgeUnavailable, match="identity"):
        load_approved_visual_grammar(path, db)
    write_pack(tmp_path, dict(PACK, extra_field="unexpected"))
    with pytest.raises(KnowledgeUnavailable, match="schema"):
        load_approved_visual_grammar(path, db)


def test_render_plan_is_bounded_stable_and_never_queued():
    a = build_render_plan(
        positive_prompt="Original impossible city at sunrise",
        negative_prompt="watermarks, smearing",
        checkpoint="art-local.safetensors", aspect_ratio="16:9", seed=369,
    )
    b = build_render_plan(
        positive_prompt="Original impossible city at sunrise",
        negative_prompt="watermarks, smearing",
        checkpoint="art-local.safetensors", aspect_ratio="16:9", seed=369,
    )
    assert a == b
    assert a["status"] == "DRAFT_NOT_SUBMITTED"
    assert a["server_contacted"] is False
    assert a["execution_enabled"] is False
    assert a["render_status"] == "not_rendered"
    assert len(a["workflow"]) == 7
    assert a["workflow"]["5"]["inputs"] == {"width": 1024, "height": 576, "batch_size": 1}
    assert a["workflow"]["9"]["class_type"] == "SaveImage"
    assert a["workflow_digest"].startswith("sha256:")


@pytest.mark.parametrize("kwargs", [
    {"checkpoint": "../../secrets.safetensors"},
    {"checkpoint": "not-a-model.ckpt"},
    {"checkpoint": "foo/bar.safetensors"},
    {"aspect_ratio": "42:1"},
    {"seed": -1},
    {"seed": True},
    {"steps": 900},
    {"cfg": float("nan")},
    {"positive_prompt": ""},
])
def test_render_plan_rejects_bad_inputs(kwargs):
    params = {"positive_prompt": "Creative concept", "negative_prompt": "",
              "checkpoint": "local.safetensors"}
    params.update(kwargs)
    with pytest.raises(ValueError):
        build_render_plan(**params)


def test_render_plan_endpoint_offline_and_configured(monkeypatch):
    monkeypatch.delenv("AGENTORA_ATELIER_CHECKPOINT", raising=False)
    client = TestClient(create_app())
    payload = {"positive_prompt": "Original luminous forest"}
    assert client.post("/api/atelier/render-plan", json=payload).status_code == 503
    monkeypatch.setenv("AGENTORA_ATELIER_CHECKPOINT", "local.safetensors")
    answer = client.post("/api/atelier/render-plan", json=payload)
    assert answer.status_code == 200, answer.text
    assert answer.json()["plan"]["server_contacted"] is False
    assert answer.json()["plan"]["workflow"]["4"]["inputs"]["ckpt_name"] == "local.safetensors"
    bad_origin = client.post("/api/atelier/render-plan", json=payload,
                             headers={"Origin": "https://evil.example"})
    assert bad_origin.status_code == 403


def test_direct_knowledge_requires_operator_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "agentora_use_mock_ollama", False)
    monkeypatch.setenv("AGENTORA_ATELIER_MODEL_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_KNOWLEDGE_ENABLED", "true")
    pack = write_pack(tmp_path)
    db = ledger(tmp_path, PACK)
    monkeypatch.setenv("AGENTORA_ATELIER_PACK_PATH", str(pack))
    monkeypatch.setenv("AGENTORA_ATELIER_REVIEWS_DB", str(db))
    client = TestClient(create_app())
    body = {"brief": {"concept": "Dream city"}, "confirm_model_call": True}
    blocked = client.post("/api/atelier/direct", json=body)
    assert blocked.status_code == 503
    ledger_db = tmp_path / "approved.sqlite3"
    # Separate fixture path to avoid collisions.
    db.rename(ledger_db)
    newdb = ledger(tmp_path, PACK, ("approved",))
    monkeypatch.setenv("AGENTORA_ATELIER_REVIEWS_DB", str(newdb))
    observed = []

    async def fake_chat(self, model, system, prompt, schema):
        observed.append(prompt)
        return {k: ("Original geometric art direction " + ("X" * required))
                for k, (required, maximum) in DIRECTOR_FIELDS.items()}

    monkeypatch.setattr("app.routers.atelier.OllamaClient.chat_structured", fake_chat)
    accepted = client.post("/api/atelier/direct", json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["receipt"]["reference_source"]["review_status"] == "approved"
    assert "Build original nested geometry" in observed[0]
