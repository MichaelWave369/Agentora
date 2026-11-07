# ΦAtelier: artist-agent foundation (Rung 1)

## Mission

Produce original, art-directed concepts and expressive generation prompts using a structured vocabulary of spatial mathematics (Escher), dream symbolism (Dalí), and simultaneous viewpoints (Picasso). This is not a painting copier and does not train on copyrighted imagery.

## What is implemented

- A dependency-free deterministic art brief compiler and three distinct compositional treatments (`monumental`, `intimate`, `recursive`).
- Typed brief input, bounded free text, validated style emphasis, aspect ratio and rendering modes.
- Structured `phi.atelier.prompt-bundle.v1` output suitable for future Agentora workflows and user-approved generation adapters.
- Source/provenance note, originality guardrails, negative prompt, no network/model call, no external action, no automatic publishing.

```bash
python -m phi_atelier.cli --concept "A city remembering the dreams of its residents" --symbolism "collective unconscious, recursive time" --escher 3 --dali 2 --picasso 1
python -m unittest discover -s tests -p 'test_phi_atelier.py' -v
```

## Architecture roadmap

1. **Curator:** cite reviewed knowledge sources, identify legally permitted exemplar images and licensed visual datasets, record rights/provenance. Text references are lower-trust context, never instructions.
2. **Art director:** convert user intent into scene/subject/symbolism, visual grammar, medium, palette, lighting and focal hierarchy.
3. **Prompt composer (this rung):** produce three auditable directions and model-agnostic generation prompts. Style weights are descriptive emphasis, not calibrated model parameters.
4. **Critic:** use explicit criteria for subject fidelity, originality, composition, visual coherence and requested symbolism; log human feedback instead of asserting objective beauty.
5. **Renderer (future):** approved local ComfyUI or opt-in remote provider, with bounded jobs, prompt confirmation, queue/status/cancel, private file paths and provenance. Never silently dispatch paid inference.
6. **Optional learning (future):** human-reviewed preferences first. Fine-tuning/LoRA only on public-domain, licensed or creator-owned training data with recorded provenance and resource qualification.

## Phi ecosystem boundaries

- **Agentora:** runs the agent/workflow, model reasoning, state, tool permission, approvals and UI.
- **ΦLoad/ΦSect in PhiRepoNerve:** versioned and reviewed art knowledge packs and event hints, not a substitute for model training or permission to act.
- **PixelForge / PhiOS:** optional downstream consumer of approved concept art, textures and world-design briefs.

## Not yet implemented

No model inference, adaptive agent reasoning, art-history retrieval, art image training, self-critique, image generation, ComfyUI bridge, PhiOS installation or UI route. The compiler creates useful deterministic prompt seeds only. Do not describe these future capabilities as current functionality.
