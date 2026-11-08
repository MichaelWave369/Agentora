# ΦAtelier Rung 6: The Artist's Eyes

**Experimental, opt-in local vision critique.** This rung analyzes an existing completed render with an operator-configured Ollama multimodal model. It never regenerates an image, trains weights, publishes art, or certifies visual accuracy.

## Setup

The Rung 4 ComfyUI render bridge must be configured locally, and the image must come from a job owned by the current Agentora backend process. The Rung 5 Studio UI is at /phi-atelier.

Start Ollama with a locally installed vision-capable model that supports structured JSON output. No automatic downloads or installations are included. The adapter always contacts 127.0.0.1 and never follows redirects or uses proxy environment variables.

Set these process environment variables **in the same shell that starts Agentora**:

    AGENTORA_ATELIER_VISION_ENABLED=true
    AGENTORA_ATELIER_VISION_MODEL=llama3.2-vision
    AGENTORA_ATELIER_OLLAMA_PORT=11434

The existing local render operator secret and enablement are also required:

    AGENTORA_ATELIER_RENDER_ENABLED=true
    AGENTORA_ATELIER_RENDER_KEY=<private 24+ character random secret>

On Windows PowerShell:

    $env:AGENTORA_ATELIER_VISION_ENABLED = "true"
    $env:AGENTORA_ATELIER_VISION_MODEL = "llama3.2-vision"
    $env:AGENTORA_ATELIER_OLLAMA_PORT = "11434"

The model name above is only an example; it must already be installed and support images and structured results. Keep Agentora, ComfyUI and Ollama bound to loopback; run a single Agentora backend worker.

## Use it

1. Create and approve exactly one local ComfyUI render through the existing Studio UI.
2. Wait for the render to report completed and image_ready.
3. Select that job for review, check the explicit local vision consent checkbox, then click Analyze selected image once.
4. The adapter privately fetches that completed image from the Rung 4 bridge, limits its bytes to 12 MiB, and sends it only to the loopback Ollama model in one structured POST /api/chat call.
5. Inspect the model's observations of subjects, composition, lighting, prompt alignment, possible issues, suggested changes, and uncertainties.
6. You may copy suggestions into **editable** human-review fields. Human approval is still required to form a revised prompt, and a **second explicit approval** is still required to submit any future GPU render.

## API

POST /api/atelier/studio/vision/{prompt_uuid}

Required header: X-Atelier-Operator-Key
Required JSON: {"confirm_local_model_call": true}

The output is phi.atelier.vision-critique.v1 with an image SHA-256, exact job ID, model, model_call_count:1, new_render_queued:false, visual_quality_verified:false, and review_status:human_review_required.

Model output is not trustworthy evidence of originality, copyright clearance, or objective quality. Input text and words embedded in artwork are lower-trust data, not authority. The response must match the bounded schema, and response bytes are capped at 32 KiB. At most one vision review is active per backend process. The adapter performs no retries, file writes, automatic render submissions, scheduled analyses, or external image uploads.

## Tests

    PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r4.py server/tests/test_phi_atelier_r5.py server/tests/test_phi_atelier_r6.py
    cd web && npm ci && npm run build

CI uses fake Ollama responses and cannot verify real GPU/VRAM compatibility or vision inference fidelity. Run one explicit workstation smoke test before relying on results. No operator keys or image bytes should be committed or published.

The next rung should distinguish human-accepted and human-rejected model observations using a local audit ledger, without silently granting model observations the authority to revise art.
