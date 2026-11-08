# ΦAtelier Rung 7: The Artist's Memory

**Human decisions are authoritative; model suggestions are not.**

Rung 7 introduces a persistent, private SQLite feedback ledger for the ΦAtelier Studio. After a completed ComfyUI image is reviewed by the optional local Ollama vision model, you can explicitly accept, reject or revise that model's suggestions. Revisions and acceptances can later be displayed as reference notes for **manual** reuse. Nothing is automatically trained, injected into a prompt, rerendered, published or transmitted to a cloud service.

## Local configuration

Requires Rung 4 local ComfyUI bridge, Rung 5 Studio, and Rung 6 optional vision critic. Use only a single Agentora backend process bound to loopback and a private operator key.

In the server process environment, enable:

    AGENTORA_ATELIER_MEMORY_ENABLED=true

Optional SQLite path:

    AGENTORA_ATELIER_MEMORY_DB=/absolute/private/path/to/phi_atelier_feedback.sqlite3

If the path is omitted, the default is ~/.agentora/phi_atelier_feedback.sqlite3. Agentora creates the ledger only when you explicitly save a human decision. The SQLite file is local and contains art prompts, model suggestions and feedback reasons, but **never the image bytes or operator key**. Keep filesystem permissions private and back it up as you would other creative work.

Example for Windows PowerShell:

    $env:AGENTORA_ATELIER_MEMORY_ENABLED = "true"
    $env:AGENTORA_ATELIER_MEMORY_DB = "$env:USERPROFILE\.agentora\phi_atelier_feedback.sqlite3"

Set the variables **before starting** Agentora. The memory feature remains disabled by default. Use a locally generated secret for AGENTORA_ATELIER_RENDER_KEY and keep the API on 127.0.0.1.

## Workflow in the Studio

1. Render an image using explicit ComfyUI authorization, then run one explicitly approved local vision critique.
2. Read its fallible observations. Rung 7 stages a digest-pinned reference to that exact job, image hash, original prompt, local model and suggestions **in process memory only**. Staging does not write to SQLite.
3. In the Artist's Memory card below the critique, select exactly one:
   - **Accept:** save the suggested improvements as reference data.
   - **Reject:** record why you did not accept the suggestion, without making it an approved reference.
   - **Revise:** save **your edited alternative** as the approved reference, while preserving the model's original suggestion for comparison.
4. Provide a reason and check the explicit human-approval checkbox, then save the decision. This makes a single append-only local ledger record.
5. Refresh the Studio memory view to read your decisions. Rejected notes appear only in history; accepted/revised notes appear in a separate manual-only guidance view. The user must click Copy to reuse a note.
6. Export JSON manually if you want a portable backup. The export excludes operator secrets and image bytes but **contains your art prompts and review notes**.

## API

All memory endpoints require the same private local render operator key and are disabled unless AGENTORA_ATELIER_MEMORY_ENABLED=true.

    POST /api/atelier/studio/memory/decision
    {
      "review_digest":"sha256:<64 lower-case hex digits>",
      "decision":"accepted|rejected|revised",
      "human_reason":"I inspected the result and ...",
      "edited_guidance":"Only for the revised decision",
      "human_confirm":true
    }

    GET /api/atelier/studio/memory
    GET /api/atelier/studio/memory/context

The first GET returns the last 50 human decisions and chain head. The second exposes **explicitly accepted and revised** suggestions for manual use, never an automatic model-injection pipeline.

The review digest is issued by the backend after a successful local vision call. It binds the source job UUID, image digest, model name, original prompt, and observations. It expires from in-memory staging after one hour or when the backend restarts; up to 16 pending reviews may be staged. Each digest may receive **one** human decision. A consumed digest cannot be reused to create conflicting decisions.

## Security and data integrity

Each saved decision includes its predecessor's SHA-256 and a canonical JSON content hash; the reader validates the **entire chain** before showing history or accepting new decisions. This detects many accidental edits or interior deletions. It is **not a tamper-proof audit log against a malicious local administrator**, does not authenticate human identity, and cannot detect malicious deletion of the entire database or a valid tail. The reviewer's button press is recorded as user-confirmed input, not a cryptographic signature.

This is deliberately a bounded single-workstation pilot, not a distributed learning system. Maximum 5,000 records, 16 outstanding reviews, one-hour staging lifetime, and constrained text sizes. Memory remains private and is not silently offered to unrelated agents.

Training performed: **no**. New renders queued: **no**. Model inference called by memory endpoints: **no**.

## Tests

    PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r5.py server/tests/test_phi_atelier_r6.py server/tests/test_phi_atelier_r7.py
    cd web && npm ci && npm run build

CI uses temporary local SQLite fixtures and simulated render/model responses. It cannot attest to your physical GPU or actual model-critique quality. Verify with an explicitly consented local workstation session before relying on the ledger.

### Next step

Build an **explicit, reversible learning/reference policy** that asks the operator which accepted notes to reuse for a specific future art brief. That should remain user-authorized and source-attributed, not silent fine-tuning.
