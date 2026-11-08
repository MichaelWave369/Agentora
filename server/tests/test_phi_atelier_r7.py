"""Rung 7: human decision gates, durable local chain, no autonomous learning."""
import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import atelier
from phi_atelier.memory import MemoryError as FeedbackMemoryError, ReviewMemory

KEY = "local-operator-key-with-32-plus-chars"
SOURCE = str(uuid4())


def make_report(job_id=SOURCE, suffix="a"):
    return {
        "job_id": job_id,
        "image_sha256": "sha256:" + suffix * 64,
        "model": "local-vision-test",
        "origin": "local_vision_model_unverified",
        "review_status": "human_review_required",
        "new_render_queued": False,
        "observations": {
            "visible_subjects": "Visible landscape",
            "specific_suggestions": "Improve foreground contrast while keeping the subject original.",
            "uncertainties": "This is only a test model observation.",
        },
    }


def stage(mem, suffix="a"):
    return mem.stage(make_report(suffix=suffix), original_prompt="An original glass city")


def decide(mem, ref, action="accepted", text="", reason="Human reviewed the visual suggestion carefully"):
    return mem.decide(
        review_digest=ref, decision=action, human_reason=reason,
        edited_guidance=text, human_confirm=True,
    )


def test_stage_never_writes_database_or_trains(tmp_path):
    path = tmp_path / "private_feedback.sqlite3"
    mem = ReviewMemory(path)
    ref = stage(mem)
    assert ref.startswith("sha256:") and len(ref) == 71
    assert not path.exists()
    assert mem.list_decisions()["entries"] == []
    assert mem.accepted_context()["notes"] == []


def test_acceptance_is_persistent_reviewed_but_no_training(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    mem = ReviewMemory(path)
    ref = stage(mem)
    entry = decide(mem, ref)
    assert entry["decision"] == "accepted"
    assert entry["approved_guidance"].startswith("Improve foreground")
    assert entry["training_performed"] is False
    assert entry["new_render_queued"] is False
    assert path.exists()
    fresh = ReviewMemory(path)
    history = fresh.list_decisions()
    assert history["verified_hash_chain"] is True
    assert history["total_entries"] == 1
    assert history["entries"][0]["review_digest"] == ref
    assert history["entries"][0]["human_reason"].startswith("Human reviewed")
    assert fresh.accepted_context()["notes"][0]["decision"] == "accepted"
    with pytest.raises(FeedbackMemoryError, match="not pending"):
        decide(mem, ref)


def test_rejected_stays_auditable_but_does_not_enter_approved_context(tmp_path):
    mem = ReviewMemory(tmp_path / "a.sqlite3")
    ref = stage(mem)
    e = decide(mem, ref, "rejected")
    assert e["approved_guidance"] == ""
    assert mem.list_decisions()["entries"][0]["decision"] == "rejected"
    assert mem.accepted_context()["notes"] == []


def test_revised_requires_operator_edits(tmp_path):
    mem = ReviewMemory(tmp_path / "feedback.sqlite3")
    ref = stage(mem)
    with pytest.raises(FeedbackMemoryError, match="edited_guidance"):
        decide(mem, ref, "revised")
    with pytest.raises(FeedbackMemoryError, match="only permitted"):
        decide(mem, ref, "accepted", "unapproved edited suggestion")
    ref = stage(mem)
    entry = decide(mem, ref, "revised", "Use a softer light transition across the foreground.")
    assert entry["approved_guidance"].startswith("Use a softer")
    assert mem.accepted_context()["notes"][0]["decision"] == "revised"
    assert mem.accepted_context()["notes"][0]["approved_guidance"] != entry["reviewed_suggestion"]


def test_human_confirm_mandatory_and_untrusted_origin_rejected(tmp_path):
    mem = ReviewMemory(tmp_path / "feedback.sqlite3")
    ref = stage(mem)
    with pytest.raises(FeedbackMemoryError, match="confirmation"):
        mem.decide(review_digest=ref, decision="accepted",
                   human_reason="Operator has inspected suggestions", human_confirm=False)
    bad = make_report()
    bad["origin"] = "verified_by_ai"
    with pytest.raises(FeedbackMemoryError, match="unverified"):
        mem.stage(bad, original_prompt="An original glass city")
    assert not mem.database.exists()


def test_tamper_and_truncation_detected_by_chain(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    mem = ReviewMemory(path)
    decide(mem, stage(mem, "a"))
    decide(mem, stage(mem, "b"), "rejected")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE feedback SET human_reason='modified outside review' WHERE id=1")
    with pytest.raises(FeedbackMemoryError, match="integrity"):
        mem.list_decisions()
    with pytest.raises(FeedbackMemoryError, match="integrity"):
        decide(mem, stage(mem, "c"))


def test_pinned_source_digest_changes_with_image_or_prompt(tmp_path):
    mem = ReviewMemory(tmp_path / "memory.sqlite3")
    a = stage(mem, "a")
    b = stage(mem, "b")
    assert a != b
    with pytest.raises(FeedbackMemoryError):
        mem.stage({"origin": "local_vision_model_unverified"}, original_prompt="x")
    with pytest.raises(FeedbackMemoryError, match="UUID"):
        mem.stage(make_report(job_id="../evil"), original_prompt="Original")
    assert not mem.database.exists()


def test_invalid_edited_text_or_reason_cannot_commit(tmp_path):
    mem = ReviewMemory(tmp_path / "feedback.sqlite3")
    ref = stage(mem)
    with pytest.raises(FeedbackMemoryError):
        decide(mem, ref, reason="short")
    with pytest.raises(FeedbackMemoryError):
        decide(mem, ref, action="revised", text="\x00invalid text with control")
    assert not mem.database.exists()


class FakeImages:
    def __init__(self):
        self.calls = 0
        self.renders = 0

    def get_job(self, job_id):
        assert job_id == SOURCE
        return {"positive_prompt": "An original glass city"}

    async def image(self, job_id):
        self.calls += 1
        assert job_id == SOURCE
        return b"\x89PNG\r\n\x1a\n" + b"image-test-pixels-123456", "image/png"


class FakeCritic:
    def __init__(self):
        self.calls = 0

    async def review(self, *, job_id, image, mime, intended_prompt):
        self.calls += 1
        assert mime == "image/png" and intended_prompt == "An original glass city"
        return make_report(job_id=job_id)


def app_with_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_KEY", KEY)
    monkeypatch.setenv("AGENTORA_ATELIER_VISION_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_MEMORY_ENABLED", "true")
    mem = ReviewMemory(tmp_path / "server-feedback.sqlite3")
    img, model = FakeImages(), FakeCritic()
    monkeypatch.setattr(atelier, "review_memory", mem)
    monkeypatch.setattr(atelier, "comfy_bridge", img)
    monkeypatch.setattr(atelier, "vision_critic", model)
    client = TestClient(create_app(), base_url="http://127.0.0.1:8088")
    return client, mem, img, model


def test_endpoints_stage_then_record_one_explicit_human_decision(monkeypatch, tmp_path):
    client, mem, image, vision = app_with_memory(monkeypatch, tmp_path)
    headers = {"X-Atelier-Operator-Key": KEY}
    vision_response = client.post(
        "/api/atelier/studio/vision/" + SOURCE,
        json={"confirm_local_model_call": True}, headers=headers,
    )
    assert vision_response.status_code == 200, vision_response.text
    ref = vision_response.json()["report"]["review_digest"]
    assert not mem.database.exists()  # No disk write on model review.
    denied = client.post("/api/atelier/studio/memory/decision", headers=headers, json={
        "review_digest": ref, "decision": "accepted",
        "human_reason": "I personally approve these suggestions", "human_confirm": False,
    })
    assert denied.status_code == 403
    assert image.calls == vision.calls == 1
    saved = client.post("/api/atelier/studio/memory/decision", headers=headers, json={
        "review_digest": ref, "decision": "accepted",
        "human_reason": "I personally approve these suggestions", "human_confirm": True,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["entry"]["training_performed"] is False
    assert image.renders == 0
    assert image.calls == vision.calls == 1  # No hidden second inference or GPU job.
    ledger = client.get("/api/atelier/studio/memory", headers=headers)
    assert ledger.status_code == 200
    assert ledger.json()["memory"]["total_entries"] == 1
    context = client.get("/api/atelier/studio/memory/context", headers=headers)
    assert context.status_code == 200
    assert context.json()["context"]["notes"][0]["approved_guidance"].startswith("Improve")
    assert context.json()["context"]["automatically_injected_into_model"] is False


def test_memory_auth_disabled_and_cross_site_fails_before_data(monkeypatch, tmp_path):
    client, mem, image, model = app_with_memory(monkeypatch, tmp_path)
    assert client.get("/api/atelier/studio/memory").status_code == 403
    headers = {"X-Atelier-Operator-Key": KEY, "Origin": "https://outside.example"}
    assert client.get("/api/atelier/studio/memory", headers=headers).status_code == 403
    monkeypatch.setenv("AGENTORA_ATELIER_MEMORY_ENABLED", "false")
    assert client.get("/api/atelier/studio/memory", headers={"X-Atelier-Operator-Key": KEY}).status_code == 404
    assert not mem.database.exists()
    assert image.calls == model.calls == 0
