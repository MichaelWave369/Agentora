# Φ Development Board R1-H · Human-carried PhiBot coding-task inspection

**Zero local installs. Zero runtime GitHub repository writes.** This is a fixed **toy Python code-change preview**, not a code-generating agent, a live GitHub issue, a PR-writing tool, or proof of code correctness. The upstream R1-G design_cpu mode remains available and unchanged.

## End-to-end browser-only trial

1. Once the Agentora R1-H PR is merged, open [Agentora Cloud Trial](https://github.com/MichaelWave369/Agentora/actions/workflows/development-board-cloud-trial.yml).
2. Click **Run workflow**, select `draft_review`, and run it manually on `main`. **No Ollama model is downloaded** for this mode.
3. Open the finished run's **Artifacts**. Download the `devboard-cloud-draft_review-...` bundle. It contains:
   - `phibot-review-packet.json`: the readable proposed Python change and strict review-only authority flags.
   - `phibot-review-packet.base64url.txt`: the **single line** to copy into PhiBot's workflow input.
   - `agentora-review-receipt.json`: a SHA-matched, self-reported packet verification result.
4. After the separate PhiBot R1-H inspector PR is merged, open [PhiBot R1-H Read-Only Agentora Task Inspection](https://github.com/MichaelWave369/PhiBot/actions/workflows/r1h-readonly-inspection.yml).
5. Click **Run workflow**, paste the entire single line from `phibot-review-packet.base64url.txt` into `packet_b64` and run it.
6. Inspect the resulting **PhiBot** `phibot-r1h-readonly-inspection-...` artifact. Its `status` must be `INSPECTED_EXACT_TOY_SCOPE_REVIEW_ONLY`, with all no-authority fields set to false.

The handoff is intentionally **operator-carried**. No cross-repository webhook, GitHub App connection, PhiBot daemon, API token, hidden upload or automated GitHub action is granted.

## What is actually being proposed?

One **fixed, versioned** source file: `examples/development-board/r1h-demo-label.py`.

The proposed preview adds a Python type check in the toy `normalize_label(value)` function and otherwise retains the exact original source. Both source versions are **text only** in the packet. The producer never modifies that source file, executes it, runs its tests or opens a PR. The target is an allowed **demo fixture only**, not a legitimate issue authorization or approval to patch production code.

The packet binds a `GITHUB_SHA` **claim**, the fixed repository and relative path, original and proposed source bytes, SHA-256 hashes, a short acceptance checklist, a domain-separated packet checksum and explicit denials for issue creation, PR creation, merge, deployment, source writes, approval and PhiBot runtime execution. The packet shape intentionally **does not match** PhiBot's seven-field `repo.steward.draft` write request.

## Inspecting vs trusting

The Agentora packet checker and the PhiBot JavaScript inspector are independent implementations of a **fixed contract**. They can reject altered code, extra fields, wrong paths, forged authority and checksum inconsistencies, but **cannot independently prove who ran GitHub Actions, that the claimed commit is the live branch tip, that source has been safely executed, or that a real human approved it**. The PhiBot side performs no GitHub API calls or model inference. `INSPECTED_EXACT_TOY_SCOPE_REVIEW_ONLY` is not a permission to write, queue, grant, merge or deploy.

The GitHub Actions token on both sides is read-only (`contents: read`), checkouts do not persist credentials, and the workflows are manual-only. Nothing here turns a model into a privileged agent.

### Test gates

- Agentora's Python tests run the real manual workflow CLI in a subprocess, confirm exact file and packet hashes, and reject tampering, changed source, wrong commit and every requested write flag.
- PhiBot's Node tests independently verify the canonical digest and fixed code preview, reject malformed base64/JSON, extra properties, injection-like replacements and all attempted write escalations. PhiBot's **normal `npm test`** now covers this inspector.
- **Separate human green field runs** are still required after merging both PRs. CI does not constitute that proof.

**Ledger Above Ego. The packet is evidence to read, never instructions to obey.**
