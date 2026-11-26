# Phi Independence R05-B — local proposal generation

Experimental; extends [R05-A](PHI_INDEPENDENCE_R05A_FORGE.md) without modifying its
existing contract. Reuses the R3 frozen task, source checks and proposal function.
One preselected existing allowlisted React file; no model-selected paths or commands.

## Windows pilot

Prepare a trusted clean Agentora checkout, a private ACL-restricted encrypted directory
outside Git, and a locally installed non-cloud Ollama model. Use R3 init as in R05-A.
Plan first (paths and model tag illustrative):

```powershell
python scripts/phi_forge_r05b.py plan D:/PhiVault/forge-task.json --source . --model qwen2.5-coder:7b --output D:/PhiVault/forge-candidate
```

Review the task, source and plan. The digest binds the entire frozen task, model tag,
exact source/prompt payload, endpoint and destination. Independently disconnect external
network access while retaining loopback. Approve only the reviewed digest:

```powershell
python scripts/phi_forge_r05b.py propose D:/PhiVault/forge-task.json --source . --model qwen2.5-coder:7b --output D:/PhiVault/forge-candidate --approve-digest YOUR_PLAN_DIGEST --confirm-offline
```

One bounded JSON request goes to 127.0.0.1:11434/api/chat. No proxy, redirects,
downloads, tools, builds or automatic retries. Provider must report completed
response and matching model tag with no tool calls. Model identity and physical
offline status are not independently verified. Socket timeout is per operation.
Use trusted installed local models; a compromised daemon could forward content.

On success a new private directory contains replacement.tsx and proposal-receipt.json.
Read the complete replacement and receipt/diff. If either is missing or malformed,
hold and use a fresh output directory; never silently reuse an interrupted output.
No encryption is provided by the script. Do not share private plans or receipts.

## Separate R05-A approval

Pass the new replacement.tsx to the existing R05-A plan command with the same
frozen spec and checkout, trusted local image ID and dedicated public npm cache.
Confirm the candidate and both patch digests match. Review the full R05-A plan
and approve its distinct digest separately before running its offline test.
The R05-B digest cannot substitute for R05-A approval. R05-A does not automatically
authenticate an R05-B receipt; it independently reconstructs its own patch plan.

No edits to the original checkout, GitHub writes, PR or merge. No model call is
made in plan. Receipt records proposal only, never tests or authority. Exact Git
blob matching and final newline requirements deliberately hold on incompatible
checkout filters. Additional actual-line counting protects against prefix-based
diff count underestimates. Source and output paths assume trusted local user and
filesystem; no malicious same-user race defense, no signed consent, no durable
replay prevention or authenticated provenance. A small diff is not necessarily safe.
No automatic R04-B review-to-task conversion; operator still freezes task manually.

Tests: PYTHONPATH=server pytest -q server/tests/test_phi_forge_r05b.py.
Real Git synthetic fixture plus mocked local provider; actual model, Docker and
offline end-to-end workstation acceptance remain unverified.
