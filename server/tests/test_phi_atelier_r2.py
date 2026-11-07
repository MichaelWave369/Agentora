"""PhiAtelier Rung 2 contract tests: no live model, no renderer, no writes."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from phi_atelier import ArtBrief
from phi_atelier.director import (
    DIRECTOR_FIELDS, DIRECTOR_SCHEMA,
    direction_receipt, prepare_direction, validate_direction,
)

BRIEF = {
    "concept": "A city watching itself awaken",
    "symbolism": "Different memories form a shared sky",
    "influences": {"escher": 3, "dali": 2, "picasso": 1},
}


def fake_proposal():
    return {
        "title": "The Memory City",
        "visual_thesis": "An original city senses its own existence through overlapping neighborhoods and a shared dawn.",
        "scene_design": "A public square opens into another scale through a vaulted archway. The street repeats but each district has a different physical rule.",
        "symbolism": "Windows are personal memories; the plaza is the shared self; dawn marks recognition and the architecture suggests continuity.",
        "composition": "Use a clear foreground silhouette, a bright center of interest, and a recursive architectural background connected by one walking path.",
        "lighting_palette": "Soft blue morning fill, warm amber windows, believable shadows and physically grounded stone and glass surfaces.",
        "positive_prompt": "Original panoramic city with nested neighborhoods, readable human-scale foreground figure, careful architectural recursion, rich atmospheric light, coherent physical materials and a luminous public plaza.",
        "negative_prompt": "No signatures, copied artworks, recognizable painting layouts, incoherent architecture, unwanted letters, watermarks or smeared figures.",
        "similarity_risks": "Avoid known impossible-stair constructions, melting timepieces, recognizable cubist portraits and compositions borrowed from museum works.",
        "self_critique": "The focal subject could be lost against repetitive architecture; strengthen the walking figure and clarify the entrance to the central plaza.",
        "improvement_actions": "Add a silhouette at the foreground, reduce secondary arches, and shift the warmest lights to the central plaza.",
    }


def test_prepare_direction_and_receipt_are_bounded_and_explicit():
    prepared = prepare_direction(ArtBrief(**BRIEF), "intimate")
    assert prepared["direction_id"] == "intimate"
    assert "A city watching itself" in prepared["model_prompt"]
    assert "model_system" in prepared
    assert prepared["model_schema"] == DIRECTOR_SCHEMA
    result = direction_receipt(prepared, fake_proposal(), model_name="gemma3:12b")
    assert result["render_status"] == "not_rendered"
    assert result["status"] == "human_review_required"
    assert result["auto_publish"] is False
    assert result["trained_on_artist_works"] is False


def test_model_response_rejects_extra_fields_blank_and_control_chars():
    original = fake_proposal()
    assert set(validate_direction(original)) == set(DIRECTOR_FIELDS)
    with pytest.raises(ValueError, match="schema"):
        validate_direction({**original, "tool_command": "delete all"})
    with pytest.raises(ValueError, match="title"):
        validate_direction({**original, "title": ""})
    with pytest.raises(ValueError, match="control"):
        validate_direction({**original, "title": "Unsafe\x00Payload"})


def test_preview_is_offline_and_validated():
    client = TestClient(create_app())
    response = client.post("/api/atelier/preview", json=BRIEF)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["model_call"] is False
    assert data["bundle"]["render_status"] == "not_rendered"
    assert len(data["bundle"]["candidates"]) == 3
    bad = client.post("/api/atelier/preview", json={**BRIEF, "influences": {"escher": -1}})
    assert bad.status_code == 422


def test_direct_is_disabled_without_explicit_operator_consent(monkeypatch):
    client = TestClient(create_app())
    monkeypatch.delenv("AGENTORA_ATELIER_MODEL_ENABLED", raising=False)
    without_confirmation = client.post("/api/atelier/direct", json={"brief": BRIEF})
    assert without_confirmation.status_code == 403
    confirmed = client.post("/api/atelier/direct", json={"brief": BRIEF, "confirm_model_call": True})
    assert confirmed.status_code == 404
    monkeypatch.setenv("AGENTORA_ATELIER_MODEL_ENABLED", "true")
    mock_mode = client.post("/api/atelier/direct", json={"brief": BRIEF, "confirm_model_call": True})
    assert mock_mode.status_code == 503


def test_direct_one_local_model_call_without_any_render(monkeypatch):
    calls = []

    async def fake_chat(self, model, system, prompt, schema):
        calls.append((model, system, prompt, schema))
        return fake_proposal()

    monkeypatch.setenv("AGENTORA_ATELIER_MODEL_ENABLED", "true")
    monkeypatch.setattr(settings, "agentora_use_mock_ollama", False)
    monkeypatch.setattr("app.routers.atelier.OllamaClient.chat_structured", fake_chat)
    client = TestClient(create_app())
    response = client.post("/api/atelier/direct", json={"brief": BRIEF, "direction": "recursive", "confirm_model_call": True})
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["origin"] == "local_ollama_response_unverified"
    assert receipt["render_status"] == "not_rendered"
    assert len(calls) == 1
    assert calls[0][3] == DIRECTOR_SCHEMA


def test_external_browser_origin_rejected_before_model_call(monkeypatch):
    monkeypatch.setenv("AGENTORA_ATELIER_MODEL_ENABLED", "true")
    monkeypatch.setattr(settings, "agentora_use_mock_ollama", False)
    client = TestClient(create_app())
    response = client.post(
        "/api/atelier/direct",
        headers={"Origin": "https://attacker.example"},
        json={"brief": BRIEF, "confirm_model_call": True},
    )
    assert response.status_code == 403


def test_malformed_model_reply_is_not_published(monkeypatch):
    async def fake_invalid(self, model, system, prompt, schema):
        return {"invalid_payload": "not json"}

    monkeypatch.setenv("AGENTORA_ATELIER_MODEL_ENABLED", "true")
    monkeypatch.setattr(settings, "agentora_use_mock_ollama", False)
    monkeypatch.setattr("app.routers.atelier.OllamaClient.chat_structured", fake_invalid)
    client = TestClient(create_app())
    response = client.post("/api/atelier/direct", json={"brief": BRIEF, "confirm_model_call": True})
    assert response.status_code == 502
