"""Deterministic, dependency-free creative brief compiler for PhiAtelier Rung 1.

This is a structured prompt-design baseline, *not* a trained art model or a
renderer. It produces reproducible original-art directions that a future agent
and an approved generation backend may refine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

STYLE_VOCABULARY = {
    "escher": {
        "discipline": "spatial mathematics",
        "techniques": "recursive architectural logic, interlocking tessellations, impossible yet internally legible transitions, multiple gravitational frames",
        "avoid": "replicating any existing staircase or lithograph",
    },
    "dali": {
        "discipline": "dream symbolism",
        "techniques": "meticulously rendered dream logic, symbolic metamorphosis, uncanny material relationships, long atmospheric depth",
        "avoid": "reproducing recognizable objects or arrangements from existing paintings",
    },
    "picasso": {
        "discipline": "plural viewpoints",
        "techniques": "simultaneous perspectives, sculptural planes, geometric reassembly, meaningful tension between profiles and frontal views",
        "avoid": "tracing recognizable compositions or character portraits",
    },
}

VARIATIONS = {
    "monumental": "Stage the concept as a sweeping panoramic environment with a coherent visual hierarchy and a human-scale anchor.",
    "intimate": "Stage the concept as a close, emotionally specific encounter with tactile detail and restrained symbolism.",
    "recursive": "Stage the concept as nested scenes at several scales; transitions must read deliberately rather than as visual noise.",
}

ORIENTATIONS = {"landscape": "16:9", "portrait": "3:4", "square": "1:1"}
RENDERING = {
    "photoreal": "Physically credible materials, cinematic natural light, grounded textures, nuanced reflections and shadows; impossible content should feel photographically tangible.",
    "fine-art": "Museum-quality mixed-media craftsmanship, intentional mark-making, rich surface character and a controlled palette.",
    "concept-art": "Production-ready environment/character visual development with clear silhouettes, focal hierarchy, and reference-friendly detail.",
}


@dataclass(frozen=True)
class ArtBrief:
    concept: str
    symbolism: str = ""
    orientation: str = "landscape"
    rendering: str = "photoreal"
    influences: Mapping[str, int] = field(default_factory=lambda: {"escher": 1, "dali": 1, "picasso": 1})
    restrictions: str = ""


def _clean(s: str, field_name: str, max_len: int = 1000) -> str:
    if not isinstance(s, str):
        raise ValueError(f"{field_name} must be text")
    s = " ".join(s.split())
    if len(s) > max_len:
        raise ValueError(f"{field_name} exceeds {max_len} characters")
    return s


def compile_brief(brief: ArtBrief) -> dict[str, Any]:
    """Compile one art direction into three distinct, deterministic render prompts."""
    concept = _clean(brief.concept, "concept")
    if not concept:
        raise ValueError("concept is required")
    symbolism = _clean(brief.symbolism, "symbolism")
    restrictions = _clean(brief.restrictions, "restrictions")
    if brief.orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be one of {', '.join(ORIENTATIONS)}")
    if brief.rendering not in RENDERING:
        raise ValueError(f"rendering must be one of {', '.join(RENDERING)}")
    if not isinstance(brief.influences, Mapping) or not brief.influences:
        raise ValueError("at least one influence is required")
    invalid = set(brief.influences) - set(STYLE_VOCABULARY)
    if invalid:
        raise ValueError(f"unsupported influences: {', '.join(sorted(map(str, invalid)))}")
    if any(type(w) is not int or w < 0 or w > 100 for w in brief.influences.values()):
        raise ValueError("influence weights must be integers from 0 to 100")
    chosen = [(name, brief.influences[name]) for name in STYLE_VOCABULARY if brief.influences.get(name, 0) > 0]
    total = sum(weight for _, weight in chosen)
    if not total:
        raise ValueError("at least one influence weight must be positive")
    techniques = [
        {
            "name": name,
            "weight_percent": round(weight / total * 100, 2),
            "discipline": STYLE_VOCABULARY[name]["discipline"],
            "visual_grammar": STYLE_VOCABULARY[name]["techniques"],
        }
        for name, weight in chosen
    ]
    grammar = "; ".join(
        f"{item['discipline']} ({item['weight_percent']}% emphasis): {item['visual_grammar']}"
        for item in techniques
    )
    guardrails = (
        "Create a genuinely original composition. Synthesize visual principles, not a copy of any existing artwork, "
        "signature, or recognizable painting arrangement. Prioritize coherent anatomy, perspective, focus, and intentional symbolism."
    )
    prompt_prefix = (
        f"Original artwork exploring: {concept}. "
        + (f"Symbolic language: {symbolism}. " if symbolism else "")
        + f"Visual synthesis: {grammar}. "
        + f"Render specification: {RENDERING[brief.rendering]} "
        + f"Aspect ratio {ORIENTATIONS[brief.orientation]}. "
        + guardrails
        + (f" Additional project constraints: {restrictions}." if restrictions else "")
    )
    candidates = [
        {"id": name, "direction": direction, "positive_prompt": f"{prompt_prefix} {direction}",
         "negative_prompt": "watermark, logo, signature, unwanted lettering, accidental collage seams, incoherent anatomy, muddy focal point, accidental duplicate objects"}
        for name, direction in VARIATIONS.items()
    ]
    return {
        "schema_version": "phi.atelier.prompt-bundle.v1",
        "title": "PhiAtelier Original Art Direction",
        "aspect_ratio": ORIENTATIONS[brief.orientation],
        "rendering": brief.rendering,
        "style_grammar": techniques,
        "candidates": candidates,
        "provenance_note": "High-level art vocabulary, not weights trained on specific artworks. Prompts do not imply permission to reproduce protected imagery.",
        "render_status": "not_rendered",
    }
