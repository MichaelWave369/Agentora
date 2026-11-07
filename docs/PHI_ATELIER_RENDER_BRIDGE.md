# ΦAtelier Rung 4: local ComfyUI render bridge

**Experimental, opt-in pilot.** This is a functioning local API integration, not a remotely exercised GPU render. It makes no cloud calls, trains no weights, publishes no assets, and does not execute without explicit operator approval.

## Contract

1. Rung 3 builds a deterministic ComfyUI workflow with SHA-256 digest. Previewing never calls ComfyUI.
2. Submit reconstructs that plan server-side and requires the exact digest, explicit approve_gpu_render=true, an operator secret, and AGENTORA_ATELIER_RENDER_ENABLED=true.
3. Checkpoint preflight fetches only ComfyUI's local /models/checkpoints. Missing checkpoint means no queue submission.
4. Submit POSTs only this known seven-node API graph to http://127.0.0.1:PORT/prompt. The host cannot be changed.
5. Get status from /history/{uuid} and /queue. Get a bounded PNG/JPEG/WebP only from the job's SaveImage node 9 via /view. A caller cannot supply an image filename or arbitrary URL.
6. Cancel only a known queued or running job with targeted /queue delete or targeted /interrupt. This is a request, not proof of cancellation.

## Windows 11 setup

Start trusted ComfyUI on 127.0.0.1:8188 with a compatible, locally installed and licensed .safetensors checkpoint. Use one Agentora backend worker, bound to 127.0.0.1.

In the shell used to start Agentora, set environment variables:

    $env:AGENTORA_ATELIER_RENDER_ENABLED = "true"
    $env:AGENTORA_ATELIER_COMFY_PORT = "8188"
    $env:AGENTORA_ATELIER_CHECKPOINT = "my-installed-model.safetensors"
    $env:AGENTORA_ATELIER_RENDER_KEY = "<your random private secret of 24+ ASCII characters>"

Generate a random secret locally with Python secrets.token_urlsafe(32); never use the placeholder value, and never commit the real value.

Then launch Agentora:

    uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088

Use a second PowerShell session with the SAME private operator secret in its environment. Preview a render with:

    $base = "http://127.0.0.1:8088/api/atelier"
    $headers = @{ "X-Atelier-Operator-Key" = $env:AGENTORA_ATELIER_RENDER_KEY }
    $inputs = @{
      positive_prompt = "An original recursive glass city at sunrise"
      negative_prompt = "watermarks, broken anatomy"
      aspect_ratio = "16:9"
      seed = 369
      steps = 24
      cfg = 7.0
    }
    $draft = Invoke-RestMethod "$base/render-plan" -Method Post -ContentType "application/json" -Body ($inputs | ConvertTo-Json -Depth 8)

Review $draft.plan.workflow and $draft.plan.workflow_digest. If you approve the exact plan:

    $approved = $inputs.Clone()
    $approved["workflow_digest"] = $draft.plan.workflow_digest
    $approved["approve_gpu_render"] = $true
    $result = Invoke-RestMethod "$base/render/submit" -Method Post -Headers $headers -ContentType "application/json" -Body ($approved | ConvertTo-Json -Depth 8)
    $promptId = $result.job.prompt_id
    Invoke-RestMethod "$base/render/$promptId/status" -Headers $headers

After status reports completed, retrieve the image explicitly:

    Invoke-WebRequest "$base/render/$promptId/image" -Headers $headers -OutFile ".\PhiAtelier-result.png"

To request targeted cancellation of a queued or running job:

    Invoke-RestMethod "$base/render/$promptId/cancel" -Method Post -Headers $headers -ContentType "application/json" -Body '{"confirm_cancel":true}'

## Limitations

The bridge keeps a private process-local ledger, one active job and up to 16 total submissions. It does not persist after process restart or coordinate multiple Agentora workers. If ComfyUI disconnects after accepting /prompt, the bridge records a submission_unknown and never automatically requeues the same workflow; inspect ComfyUI manually before retrying. A cancellation request is not independently verified as completed. The endpoint only previews output images after they exist: it does not run vision critique or iterative refinement yet.

Protect the operator key; keep both services bound to loopback. No automatic publication. Do not run unreviewed custom node bundles or checkpoints.

## Tests

    PYTHONPATH=.:server pytest -q server/tests/test_phi_atelier_r2.py server/tests/test_phi_atelier_r3.py server/tests/test_phi_atelier_r4.py

Rung 4 tests use an in-memory httpx MockTransport rather than invoking a GPU.

See official ComfyUI server routes: https://github.com/Comfy-Org/docs/blob/main/development/comfyui-server/comms_routes.mdx
