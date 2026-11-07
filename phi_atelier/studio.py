"""Human-led image critique -> bounded next-draft prompt, with no model/GPU action.

All text is user-authored review data. Scoring is descriptive, never a claim
that visual quality has been verified by a model or a trained critic.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Mapping

CRITERIA = (
    "subject_clarity",
    "composition",
    "symbolic_coherence",
    "material_light",
    "originality",
)
MAX_PROMPT = 3000
MAX_NOTE = 1000
MAX_ACTION = 700


def _text(value: Any, label: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = " ".join(value.strip().split())
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be {'1' if required else '0'}..{maximum} characters")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def prepare_revision(
    *,
    original_prompt: str,
    scores: Mapping[str, int],
    observations: str,
    requested_changes: str,
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    """Return a human-reviewable revision. Never dispatch generation."""
    prompt = _text(original_prompt, "original_prompt", MAX_PROMPT)
    notes = _text(observations, "observations", MAX_NOTE, required=False)
    changes = _text(requested_changes, "requested_changes", MAX_ACTION)
    if not isinstance(scores, Mapping) or set(scores) != set(CRITERIA):
        raise ValueError("scores must contain the five exact rubric criteria")
    if any(type(scores[key]) is not int or not 1 <= scores[key] <= 5 for key in CRITERIA):
        raise ValueError("every score must be an integer from 1 to 5")
    if parent_job_id is not None:
        try:
            normalized = str(uuid.UUID(parent_job_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("parent_job_id must be a canonical UUID") from exc
        if normalized != parent_job_id:
            raise ValueError("parent_job_id must be a canonical UUID")
    else:
        normalized = None
    weakest = sorted(CRITERIA, key=lambda key: (scores[key], CRITERIA.index(key)))[:2]
    # Descriptive scores, not causal or objective assessments of the pixels.
    suffix = (
        " HUMAN-REVIEWED REVISION (next original artwork, do not copy prior image): "
        + changes + ". "
        + "Focus improvements: " + ", ".join(x.replace("_", " ") for x in weakest)
        + ". Retain the original subject and compositional intent unless the revision says otherwise."
    )
    if len(prompt) + len(suffix) > MAX_PROMPT:
        raise ValueError("revised prompt would exceed 3000 characters; shorten the original prompt")
    revised = prompt + suffix
    receipt = {
        "schema_version": "phi.atelier.human-revision.v1",
        "parent_job_id": normalized,
        "rubric": {key: scores[key] for key in CRITERIA},
        "observations": notes,
        "requested_changes": changes,
        "weakest_criteria": weakest,
        "original_prompt": prompt,
        "revised_prompt": revised,
    }
    digest = "sha256:" + hashlib.sha256(_canonical(receipt)).hexdigest()
    return {
        **receipt,
        "review_digest": digest,
        "origin": "human_report_unverified",
        "review_status": "recorded_in_response_not_persisted",
        "render_status": "not_rendered",
        "next_render_requires_approval": True,
        "visual_quality_verified": False,
    }
