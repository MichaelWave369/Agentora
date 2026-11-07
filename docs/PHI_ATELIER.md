# ΦAtelier: artist-agent foundation (Rung 1 + Rung 2 proposal)

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

## Rung 2: local-model art director (proposed in this PR)

Agentora now has an optional text-only API and a marketplace template for a
Curator → ArtDirector → ArtCritic team. The template defines agent roles; it is
**not installed automatically** and does not confer tool permissions.

**Offline preview, no model call**:

```bash
curl -X POST http://127.0.0.1:8088/api/atelier/preview \
  -H 'Content-Type: application/json' \
  -d '{"concept":"A recursive forest of shared memories","symbolism":"Dream and waking overlap","influences":{"escher":3,"dali":2,"picasso":1}}'
```

**Optional local Ollama art direction** (requires the operator to explicitly
enable it in the Agentora server environment, with a real local Ollama model):

```bash
export AGENTORA_ATELIER_MODEL_ENABLED=true
export AGENTORA_USE_MOCK_OLLAMA=false
export OLLAMA_URL=http://127.0.0.1:11434
export AGENTORA_CHAT_MODEL=gemma3:12b
# Start the Agentora server with these settings, then:
curl -X POST http://127.0.0.1:8088/api/atelier/direct \
  -H 'Content-Type: application/json' \
  -d '{"brief":{"concept":"A city reflecting on its own existence","symbolism":"The shared unconscious"},"direction":"recursive","confirm_model_call":true}'
```

The endpoint uses Agentora's existing Ollama client and requests strict structured
JSON. It validates the model response and returns an **unreviewed** direction
receipt, including a candid critique and improvement plan. This is one model
inference per explicit request, **not** an autonomous iterative loop.
Malformed output is rejected instead of displayed as authoritative.
A browser request from a nonlocal Origin is refused; keep the service
bound to loopback and never expose this route to the public internet.

### ΦLoad curation pack

The companion `create.visual-grammar` knowledge pack in PhiRepoNerve contains
museum-sourced **high-level principles**, plus source URLs, for human approval.
It remains **unreviewed by default** and is **not automatically ingested** into
Agentora. The operator must inspect and explicitly approve its exact content
digest using PhiRepoNerve's existing `reviews approve` workflow before any
future approved-only model bridge is developed. Source references are not
permissions to copy images or to construct a training dataset.

### Tests and boundaries

```bash
python -m unittest discover -s tests -p 'test_phi_atelier.py' -v
PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r2.py
```

No artist-specific model weights were trained. No image was generated, no UI
renderer was connected, no external knowledge retrieval is performed by the
endpoint, and no file, GitHub, marketplace-install or publishing side effects
occur in these preview/direct calls. Human evaluation and a consented local
ComfyUI adapter are later rungs. Do not describe these future capabilities as current functionality.


## Rung 3: reviewed ΦLoad knowledge and ComfyUI draft workflow

The optional Rung 3 knowledge bridge uses the **same local PhiRepoNerve v1
pack digest and approval ledger semantics**, including checking the entire
hash-chained review history. Missing approval, a changed pack or an explicit
revocation blocks knowledge-assisted direction. The gate uses standard-library
read-only SQLite and does not import or execute pack files.

### Review the real pack on your workstation

From your PhiRepoNerve checkout:

```bash
python -m phireponerve.cli reviews status
python -m phireponerve.cli reviews approve --pack create.visual-grammar --reason "I inspected the original-art guidance and source links"
python -m phireponerve.cli chamber assemble --pack create.visual-grammar
```

**The agent never grants itself approval.** Human review must happen on the
local machine. The review ledger is **not** a cryptographic identity or
tamper-proof signature against a compromised machine.

Configure the Agentora server process environment on the same machine:
```bash
AGENTORA_ATELIER_KNOWLEDGE_ENABLED=true
AGENTORA_ATELIER_PACK_PATH=/absolute/path/to/PhiRepoNerve/phireponerve/packs/create.visual-grammar.json
AGENTORA_ATELIER_REVIEWS_DB=/absolute/path/to/.phireponerve/pack_reviews.sqlite3
```

These are configuration values, not shell commands. Supply Windows absolute
paths when running Windows. Enabling the knowledge gate with a missing
file or unapproved pack fails closed (HTTP 503); disabled mode keeps the
Rung 2 base prompt composer working. The source ID, version, digest and review
status appear in the model proposal receipt. The reference material remains
lower-trust creative context and never becomes an instruction authority.

### ComfyUI API workflow preview (no render)

PhiAtelier now creates an exact JSON *draft* of ComfyUI's basic
CheckpointLoaderSimple → CLIPTextEncode → EmptyLatentImage → KSampler →
VAEDecode → SaveImage text-to-image graph. The graph is content-digested
and constrained to one image, bounded latent sizes, seed, step count, and CFG.
A default API-compatible graph is **not proof** of checkpoint compatibility,
license rights, memory sufficiency or rendering success.

Set `AGENTORA_ATELIER_CHECKPOINT` to the name of a locally installed,
trusted `.safetensors` checkpoint (just its filename, no directories):

```bash
AGENTORA_ATELIER_CHECKPOINT=my-approved-model.safetensors
```

Then, with Agentora running on loopback:

```bash
curl -X POST http://127.0.0.1:8088/api/atelier/render-plan \
  -H 'Content-Type: application/json' \
  -d '{"positive_prompt":"Original recursive glass city at sunrise","negative_prompt":"watermarks, broken architecture","aspect_ratio":"16:9","seed":369,"steps":24,"cfg":7.0}'
```

The response includes an inspectable `workflow`, SHA-256 digest,
`status: DRAFT_NOT_SUBMITTED`, `execution_enabled: false` and
`server_contacted: false`. This endpoint **does not call ComfyUI**.
A subsequent rung will need a separately authorized, locally bound
queue adapter and a human-reviewed checkpoint before any GPU job runs.
Do not expose Agentora or ComfyUI outside the workstation.

ComfyUI API-format nodes were checked against their official reference
example: https://github.com/comfyorg/comfyui/blob/master/script_examples/basic_api_example.py

### Test
```bash
PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r2.py server/tests/test_phi_atelier_r3.py
```

No generated images, model fine-tuning, background job scheduling, third-party
image uploads or automatic publishing are part of Rung 3.
