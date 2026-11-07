# ΦAtelier Rung 5: The Artist's Studio

**Scope:** an actual local-first React art workspace, an operator-authenticated in-process render gallery, a human-review rubric, and a no-execution prompt revision endpoint.

Rung 5 is **not** an autonomous art model, trained image generator, automatic vision critic, or permanent cloud gallery. It makes the existing Rung 3 plan and Rung 4 ComfyUI bridge usable through a focused workstation UI while leaving final creative judgment and render authorization to the person using it.

## Navigate

Start Agentora locally on \`127.0.0.1:8088\` and run the existing Vite web front end. Open **/phi-atelier** in the local web UI. The API defaults to \`http://127.0.0.1:8088\` for this page, or honors \`VITE_API_URL\` at build time.

ComfyUI must separately run on \`127.0.0.1:8188\`, with a trusted compatible local checkpoint. Configure the Rung 4 variables from [Rung 4 setup](PHI_ATELIER_RENDER_BRIDGE.md), including:

- \`AGENTORA_ATELIER_RENDER_ENABLED=true\`
- \`AGENTORA_ATELIER_RENDER_KEY\` as a private random ASCII secret of 24+ characters
- \`AGENTORA_ATELIER_CHECKPOINT\` as your installed safetensors checkpoint filename
- \`AGENTORA_ATELIER_COMFY_PORT=8188\` or another local ComfyUI port

Never commit your operator key, expose the ComfyUI server to the internet, or paste credentials into shared screenshots. The Studio key is held in **component memory only**, not localStorage, cookies, URLs, or exported feedback.

## Work through the studio

1. **Composition:** enter the positive and negative prompts, image ratio, seed, step count, and CFG. Click Preview exact ComfyUI workflow. The API returns a deterministic Rung 3 graph, with exact SHA-256 digest, but runs no GPU work.
2. **Authorize:** enter your separate local render key, inspect the graph and digest, explicitly check the approval box, then click Submit one render. Editing any plan parameter clears the previous preview/approval. One GPU render can be queued per accepted request.
3. **Gallery:** Refresh local gallery lists at most 16 job receipts from the current backend process. Check status manually. Only finished jobs can load private image bytes, and only on request.
4. **Compare:** select two jobs and display their images side by side. The images stay inside browser-generated object URLs and are revoked when the page is closed.
5. **Critique:** choose a job, score subject clarity, composition, symbolism, lighting/materials and originality from 1–5, add observations and requested changes. The revision endpoint compiles those human notes into an original next-draft prompt with a content digest.
6. **Revision:** clicking Create revised prompt populates the input and moves to the next seed. It **clears render approval** and never queues a render. Run preview again, inspect it, and approve one new render if desired. Human review records can be exported as bounded JSON, without operator key or image bytes.

## API added

- \`GET /api/atelier/studio/jobs\`: operator-key-protected process-local job snapshot, no new ComfyUI request, with \`persistent: false\`.
- \`POST /api/atelier/studio/revision\`: pure, bounded no-model/no-render human review transformation, returning \`phi.atelier.human-revision.v1\`, \`human_report_unverified\`, and \`next_render_requires_approval: true\`.

The revision response does not imply that pixels were analyzed by a model. A person must actually view and evaluate the image. Notes and scores are not automatically persisted in Agentora; use Export feedback JSON before closing the page.

## Security and reliability

The Rung 4 job ledger survives only as long as the single backend process. A restart loses the list, not necessarily jobs still running inside ComfyUI. Job cancellation requests may take time and do not prove cancellation. The Studio never polls automatically, publishes images, uploads prompts, or launches additional GPU jobs as a side effect of critique or comparison.

If the browser page is opened from a different host or served publicly, operator-protected render endpoints refuse it; run on loopback only. If you use the Vite development server, ensure browser origin is localhost or 127.0.0.1. A single Agentora backend worker is required.

## Tests

    PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r2.py server/tests/test_phi_atelier_r3.py server/tests/test_phi_atelier_r4.py server/tests/test_phi_atelier_r5.py
    cd web && npm ci && npm run build

GitHub CI uses fake HTTP transports and tests pure review transformations; it **does not qualify the real local GPU, checkpoint compatibility, output quality, or ComfyUI installation**. Perform a one-job, operator-approved workstation smoke test before relying on the Studio.

## Next

Rung 6 should add **explicit opt-in visual critique** with a local multimodal model and a user-reviewed result. It must distinguish model guesses from image evidence, avoid automatic approval or re-render loops, and preserve licenses/provenance for any future fine-tuning.
