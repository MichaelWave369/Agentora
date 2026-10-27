# Φ Development Board R1-E · Browser-only GitHub Actions pilot

**You do not have to install Agentora, Ollama, Python, Git, Docker, or anything else on your computer to run this demonstration.** GitHub Actions creates an ephemeral hosted computer for each manually requested run. The default demonstration needs no model. An optional experimental lane pulls and runs a small public Qwen model in a temporary cloud container.

These are **manual trials**, not unattended bots, production builds, hosted websites or a long-running model service.

## Run from any browser after this PR has been merged

1. Visit the [Agentora cloud trial workflow](https://github.com/MichaelWave369/Agentora/actions/workflows/development-board-cloud-trial.yml).
2. Click **Run workflow**. Use the `main` branch. GitHub requires the new workflow to be on the repository's default branch before this button is available.
3. Leave **mode: fixture** (recommended for your first trial) and click **Run workflow** again to start the job.
4. Open the new workflow run. The checks should show the frozen example specification, a fixed-function worker generating one HTML file on GitHub's temporary runner, and a separate verifier process checking the exact output.
5. Once the job finishes, scroll to **Artifacts** on its run page and download **devboard-cloud-fixture-[run number]**. Inspect `cloud-report.json`, the frozen spec and `index.html` from the downloaded zip.

This artifact is a **downloadable trial result**, NOT a public GitHub Pages site or production release. It is attached to that run for 7 days.

**Optional experimental model trial:** Run the workflow again and select **mode: ollama_cpu**. On the temporary GitHub runner, the workflow downloads the official Ollama Docker image and the small public `qwen3:0.6b` model, starts it there on loopback, then asks it to choose **one visual theme from exactly three allowed names** (`aurora`, `arcade`, `slate`). The model does **not** write HTML, CSS, JavaScript, shell commands or repository code in this small-model mode. A deterministic, escaping HTML builder applies an allowlisted palette, then a separate verifier checks the exact frozen spec and rendered HTML. A second verifier rechecks it before publishing the review file. This is real model-driven theme selection, **not a demonstration that Qwen wrote the webpage**. If the model refuses or returns malformed JSON, the run remains **HELD**, records a bounded stage and diagnostic code in `cloud-report.json`, and uploads no rejected HTML. A passing artifact is exported as `untrusted-model-proposal.html.txt` for manual inspection, not opened or deployed.

GitHub-hosted Actions minutes/storage and downloads may count against your account's GitHub plan or quotas, especially in private repositories or on repeated model runs. Use the fixture lane first.


**Run #40600109086 diagnosis:** The cloud Ollama image and Qwen3 model downloaded successfully, but the prior free-form HTML proposal was rejected by the combined builder/verifier gate. The original receipt did not expose enough detail to identify which one refused it. The R1-F cloud mode is intentionally redesigned around a bounded theme choice and stage-coded failure reports. This is a new experiment that needs its own successful manual Actions run; the earlier red run has not been reclassified as passing.

## Source and access controls

- New workflow: `.github/workflows/development-board-cloud-trial.yml`.
- Trigger: **only `workflow_dispatch`**. No automatic push, PR, schedule, inbound model prompt or public internet job-submission endpoint.
- GitHub token scope: **contents read only**. Checkout does not persist credentials.
- Task spec: fixed, versioned public demo `examples/development-board/r1b-fixture-spec.json`, which is hashed during the run. No user-supplied command, custom repo path, model name, artifact destination or arbitrary prompt input.
- Fixture lane: Python built into hosted runner; two separate subprocesses, no model downloads.
- Model lane: CPU-constrained public Ollama Docker image, fixed loopback service and small public model. This is an external image/model download on GitHub's machine, not your PC.
- Outputs: bounded scratch artifacts, hash and a **self-reported** review receipt. Held output exports only the refusal report, never a held untrusted HTML file.
- GitHub actions: **no issue, PR, branch, repository file, approval or deployment writes**. No auto-merge, no GitHub Pages publishing. A merged PR is required to make the new manual workflow available on `main`, but the workflow itself never merges anything.
- Acceptance vocabulary: `STATIC_REVIEW_READY_NOT_AUTHORIZED` means only the bounded local static checks passed. It cannot certify model correctness, human usability, browser safety, CI authenticity beyond GitHub's own job display, cryptographic actor identity or production readiness. `eligible_for_merge=false` always.
- Retention: 7 days for uploaded run artifacts. Any personal/private information must **not** be added to the public example spec; the workflow, logs and artifacts will contain publicly reviewable project test data.
- Security limits: the official Docker image tag is mutable; the external image/model supply chain is not independently pinned/attested in this experiment. The model runs on a single hosted runner with subprocesses sharing that runner; this does **not** create a hardened multi-party trust boundary. Do not run untrusted code from a stranger's PR through this workflow.

## What this does not replace

R1-C/R1-D still support local Ollama for people who want it. R1-E adds an **alternative**, not a requirement to switch away from GitHub-first work. The cloud trial does not yet connect the nine declarative skills to PhiBot's scoped real-source-code patch mechanism; it exercises the safe plan → build/propose → verify → human review flow only.

## Test verification

The ordinary CI workflow tests the cloud controller's public fixture path with **real child processes**, refuses invalid modes and fake authority, confirms model rejects do not upload unsafe candidate HTML, and inspects the manual-only action workflow. CI does not pull a Docker model or spend GPU/CPU inference time on every PR; that happens only after an operator clicks the optional manual model mode.

**People Above Profit. Ledger Above Ego. Your choice to test remains explicit, and your computer stays untouched.**
