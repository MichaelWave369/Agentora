# Φ Development Board R1-C: local Ollama proposal lane

**New guided field-test option:** [DEVELOPMENT_BOARD_R1D_FIELD.md](DEVELOPMENT_BOARD_R1D_FIELD.md) provides an operator-confirmed, single-command Windows local model preflight, run, and receipt recheck. The lower-level R1-C commands below remain supported.

**Scope:** This rung adds a real, opt-in local model-generated static HTML proposal to Agentora's controlled scratch builder/verifier design. It does **not** connect to PhiBot's governed PR writer yet, and it is not an autonomous repo-coding worker, a secure sandbox, an independent signed verifier, or permission to merge. GitHub, GitPorch and PhiOS are not contacted.

## First run on your own machine

Use a local Agentora checkout, Python 3.12+, and separately installed Ollama running at 127.0.0.1:11434 with an already installed model. The default identifier is qwen3.5:9b. Use the --model option to choose another locally installed model. This command does not pull or download models.

In Windows PowerShell:

    cd <your-local-Agentora-checkout>
    $env:PYTHONPATH = "server"
    ollama list
    python -m app.services.development_board.r1c_cli plan examples/development-board/r1b-fixture-spec.json

Inspect the example specification before proceeding. The plan command performs no network request, invokes no model and writes no scratch files. It prints a 64-character frozen_spec_digest. To authorize only this task, enter that exact digest and supply the separate explicit approval flag:

    python -m app.services.development_board.r1c_cli run examples/development-board/r1b-fixture-spec.json --approve-spec-digest <copy-exact-64-character-digest> --i-approve-local-model

The run command contacts local Ollama only after exact digest and input validation. It creates a new temporary workspace, freezes the approved spec, asks the model for one static HTML proposal, and independently verifies the exact saved bytes with the R1-B verifier. Only a passing verifier report plus parent post-verification hash check can create review-receipt.json.

### Local workspace contents

- frozen-spec.json: canonical spec
- artifact/index.html: untrusted model proposal
- review-receipt.json: written ONLY when the separate static verifier passes

A rejected proposal may leave an artifact but is untrusted and potentially unsafe. **Never open, execute, serve, or deploy a rejected artifact.** Inspect the bytes as text or delete the disposable folder after reviewing the refusal. The runner does not open a browser or execute generated HTML.

Even a passing run returns REVIEW_READY_NOT_AUTHORIZED. It is a locally self-reported static check, not a proof of production safety, security, independently witnessed verification or permission to merge.

## Trust boundaries

- Input is R1-B's strict five-field frozen JSON specification, with no arbitrary commands, target paths, URLs, tool grants or executable task instructions.
- One HTTP POST to the fixed host 127.0.0.1 and an explicitly validated port at /api/chat. Python stdlib HTTPConnection uses no proxy and follows no redirects. No cloud providers, remote repositories or model downloads.
- Response JSON may contain only an html string and summary string; content stays under 12 KiB and must pass all frozen-spec/static HTML verifier rules.
- Only a new scratch workspace and an exclusively created index.html are written. No existing files, Git branches, PRs, issues or user project files are changed.
- Model receives only the bounded approved spec and its digest. Never place private information, passwords, access keys or proprietary code in a spec.
- Reduced child process environment is not an OS sandbox. Ollama may itself run with the local user's privileges, and Python processes share the OS account. This is not safe isolation for arbitrary untrusted code.
- No API/Streamlit endpoint dispatches workers. This feature runs only when a user explicitly enters the CLI command locally. There is no autonomous scheduling, repair loop, merge or deployment.
- Every outcome retains eligible_for_merge=false, automatic_merge=false and unauthenticated actor identity.

## Automated tests

    AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=server pytest -q server/tests/test_development_board_r1c.py

CI runs a fake Ollama HTTP endpoint on a disposable localhost port and executes the real model worker and separate verifier as child processes. It checks forged scripts, stale specs, invalid model identifiers, incorrect HTTP status or MIME, redirects, credential inheritance, oversized results and approval guards. CI does NOT call a real model; a real Windows 11 field run and human-observed Code Brown trial are required before relying on it.

## Next controlled qualification gates

1. Run the sample locally on Windows against a previously installed Ollama model; capture a redacted local-self-report and inspect a passing HTML candidate.
2. Complete the human-observed Code Brown test, including recognition of held/untrusted proposals.
3. Connect an explicitly authorized PhiBot single-target draft-PR builder behind the governance boundary for ONE disposable allowlisted repo.
4. Keep GitPorch's exact-commit tests and independently retrieved evidence separate. Require an OS sandbox and separate identity before accepting untrusted external code. Never allow an auto-merge.

**Ledger Above Ego: the model proposes, the verifier checks, the human decides.**
