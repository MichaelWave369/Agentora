"""Human-led Rung 5 gallery + revision contract tests. No GPU or model calls."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routers import atelier
from phi_atelier.studio import CRITERIA, prepare_revision
from phi_atelier.comfy_bridge import ComfyRenderBridge

RUBRIC = {key: 3 for key in CRITERIA}
REVIEW = {
    "original_prompt": "Original architectural dreamscape with a central figure.",
    "scores": RUBRIC,
    "observations": "The geometry is elegant, but the central figure needs contrast.",
    "requested_changes": "Give the figure a warm silhouette and reduce the complexity of secondary arches",
}


def test_human_review_prepares_only_an_unrendered_draft():
    original = dict(REVIEW)
    output = prepare_revision(**original)
    assert output["schema_version"] == "phi.atelier.human-revision.v1"
    assert output["render_status"] == "not_rendered"
    assert output["next_render_requires_approval"] is True
    assert output["visual_quality_verified"] is False
    assert output["origin"] == "human_report_unverified"
    assert output["review_status"] == "recorded_in_response_not_persisted"
    assert "reduce the complexity" in output["revised_prompt"]
    assert output["review_digest"].startswith("sha256:")
    assert output == prepare_revision(**original)


def test_human_review_requires_valid_exact_rubric():
    for value in [
        {**RUBRIC, "extra": 4}, {key: 5 for key in list(CRITERIA)[:-1]},
        {**RUBRIC, "subject_clarity": 0},
        {**RUBRIC, "subject_clarity": 6},
        {**RUBRIC, "subject_clarity": True},
        {**RUBRIC, "subject_clarity": "4"},
    ]:
        with pytest.raises(ValueError):
            prepare_revision(**{**REVIEW, "scores": value})


def test_revision_rejects_missing_changes_or_long_prompts():
    with pytest.raises(ValueError):
        prepare_revision(**{**REVIEW, "requested_changes": "   "})
    with pytest.raises(ValueError, match="3000"):
        prepare_revision(**{**REVIEW, "original_prompt": "a" * 2999})
    with pytest.raises(ValueError, match="UUID"):
        prepare_revision(**{**REVIEW, "parent_job_id": "not-a-uuid"})


def test_revision_explicit_parent_and_score_order():
    parent = str(uuid4())
    review = prepare_revision(**{
        **REVIEW,
        "parent_job_id": parent,
        "scores": {**RUBRIC, "originality": 1, "composition": 2},
    })
    assert review["parent_job_id"] == parent
    assert review["weakest_criteria"] == ["originality", "composition"]
    assert review["rubric"]["originality"] == 1


def test_revision_api_has_no_side_effects(monkeypatch):
    client = TestClient(create_app())
    output = client.post("/api/atelier/studio/revision", json=REVIEW)
    assert output.status_code == 200, output.text
    assert output.json()["revision"]["render_status"] == "not_rendered"
    assert output.json()["revision"]["next_render_requires_approval"] is True
    origin_blocked = client.post(
        "/api/atelier/studio/revision",
        json=REVIEW,
        headers={"Origin": "https://outside.example"},
    )
    assert origin_blocked.status_code == 403


def test_gallery_requires_operator_key_and_returns_only_session_jobs(monkeypatch):
    monkeypatch.setattr(atelier, "comfy_bridge", ComfyRenderBridge())
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_ENABLED", "true")
    monkeypatch.setenv("AGENTORA_ATELIER_RENDER_KEY", "exact-secret-with-length-at-least-24")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8088")
    assert client.get("/api/atelier/studio/jobs").status_code == 403
    with_key = client.get("/api/atelier/studio/jobs", headers={
        "X-Atelier-Operator-Key": "exact-secret-with-length-at-least-24",
    })
    assert with_key.status_code == 200
    assert with_key.json() == {
        "ok": True, "items": [], "scope": "process_local", "persistent": False,
    }
    hostile = client.get("/api/atelier/studio/jobs", headers={
        "X-Atelier-Operator-Key": "exact-secret-with-length-at-least-24",
        "Origin": "https://outside.example",
    })
    assert hostile.status_code == 403
