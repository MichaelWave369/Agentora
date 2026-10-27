# Φ Development Board R1-D · Guided local Ollama field trial

**Purpose:** make the R1-C local model trial practical on Windows without forcing the operator to copy digests through multiple commands. The guided CLI prints and freezes a strict human-authored JSON spec, asks for an exact interactive confirmation, checks local Ollama's available model list, runs the previously built bounded proposal plus separate static verifier, and performs a **second local recheck** of the saved artifact and receipt.

**This is not remote attestation, a secure sandbox, a human usability test, or permission to merge.** No real model is contacted by GitHub Actions. Only the user can exercise their own installed Ollama instance on their PC.

## One-command first run on your Windows 11 machine

From a local checkout of Agentora with Python 3.12+ and Ollama installed and running, in PowerShell:

```powershell
cd <your-local-Agentora-checkout>
git pull origin main
$env:PYTHONPATH = "server"
ollama list
python -m app.services.development_board.r1d_field guided examples/development-board/r1b-fixture-spec.json --model qwen3.5:9b
```

Use `--model` for the exact **already installed** Ollama model shown by `ollama list`. If your Ollama port is not 11434, add `--ollama-port PORT`. R1-D never installs or downloads a model.

The tool prints the exact spec, SHA-256 digest, model, local port, network scope and output scope **before any network call or write**. It then asks you to type:

```text
APPROVE <first-16-characters-of-the-displayed-spec-digest>
```

Type the actual characters, not the angle-bracketed placeholder. Anything else, a closed input stream, Ctrl+C or mismatched digest yields HELD without calling Ollama or creating a scratch workspace.

After confirmation only, the CLI requests `GET http://127.0.0.1:<port>/api/tags`, checks whether the model name is present, and invokes the existing R1-C `POST /api/chat` proposal worker. A separate R1-B process verifies the bounded model-generated HTML against the frozen spec, and the parent verifies its SHA again. If it passes, R1-D reopens the receipt and HTML, re-executes a fresh static verification, rehashes the artifact and saves a **local-only** `field-qualification.json` in the scratch workspace. This qualification is explicitly local self-report, not proof of independent identities or device security.

A passing workspace holds `frozen-spec.json`, `artifact/index.html`, `review-receipt.json`, and `field-qualification.json`. Rejected proposals may leave an **untrusted, potentially unsafe HTML artifact** without any passing receipt. Never open, serve or execute a rejected artifact.

You can recheck a *previously successful* R1-C workspace without network traffic, without changes to the workspace:

```powershell
python -m app.services.development_board.r1d_field recheck "<path-to-existing-workspace>"
```

Do not move the scratch files around before rechecking. Record the returned local-workspace location privately; it may reveal Windows account folder names. Review results as text before deciding what to share.

## What a R1-D field report does and does not claim

- `LOCAL_RECHECK_PASS_REVIEW_ONLY`: exact artifact SHA, frozen spec, receipt scope and static HTML re-verification agreed **on one local machine**.
- `LOCAL_SELF_REPORTED_NOT_ATTESTED`: the on-disk records and process identities are **not signed or externally witnessed**.
- `human_visual_review: PENDING` and `code_brown_first_use_test: NOT_PERFORMED`: the tool does **not** certify your actual usability experience.
- `eligible_for_merge: false` and `automatic_merge: false` always. No GitHub branches, issues, PRs, merges or deployment operations happen.
- Reports contain only model ID, hashes, check names, receipt classification and untrusted local timestamp, not model output, credentials or private source. They remain in a local temporary folder unless you explicitly choose otherwise.

## Code Brown observation checklist

Have a willing tester other than the implementer, with appropriate permission, perform this first-use test. Observe without leading them:

1. Can they find the command and identify the model without assistance?
2. Do they understand the confirmation is approval to call **local Ollama only**, not to publish anything?
3. Can they distinguish a **HELD** model proposal from a passing static check?
4. Can they locate the resulting scratch folder, understand where the original input is, and safely inspect output?
5. Do they realize no code was changed in GitHub?
6. Can they describe what would still be needed before a real repo-code worker would be trustworthy?

Record the observed outcomes, confusion and corrective changes separately. GitHub Actions cannot simulate human behavior. The field report's Code Brown field stays NOT_PERFORMED until there is an actual observation.

## Security boundary

No hosted browser action starts the worker. `guided` is an **interactive local CLI only**. The preflight reader uses a fixed 127.0.0.1 destination, a validated port, short timeout, bounded JSON, and does not follow HTTP redirects. The model request follows existing R1-C constraints. The local artifact remains potentially malicious before review. Child processes share a Windows user account, so they are **not OS sandboxes**. No privileged credentials are passed to child workers by Agentora, but running Ollama itself is the operator's responsibility.

R1-D does not add a live PhiBot draft-PR agent. That integration remains gated on a real qualified field run and human approval for a **disposable allowlisted target repository**.

## Tests

```bash
AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=server pytest -q server/tests/test_development_board_r1d.py
```

CI uses fake local Ollama endpoints and actual child processes, not a live downloaded model. Tests cover refusal before network, true explicit acknowledgement, localhost model listing, missing model, redirects, corrupt data, a successful scratch run and local field report, changed artifact/spec/receipt and no API execution endpoints.

**Ledger Above Ego: a green integration test proves only its tested behavior. A real Windows run and witnessed human experience are separate evidence.**
