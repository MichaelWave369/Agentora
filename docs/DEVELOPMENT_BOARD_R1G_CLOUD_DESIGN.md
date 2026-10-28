# Φ Development Board R1-G · Model-driven bounded cloud design

**Runs entirely in GitHub Actions.** No Python, Ollama, Docker, terminal or checkout is required on the user's PC. R1-G extends the successful R1-F cloud model trial without replacing the working `fixture` or `ollama_cpu` modes.

## Run it in your browser

After PR #48 (or whichever number GitHub assigned this R1-G PR) is merged:

1. Visit [Agentora Cloud Trial](https://github.com/MichaelWave369/Agentora/actions/workflows/development-board-cloud-trial.yml).
2. Select **Run workflow**, using branch `main`.
3. Choose **`design_cpu`** and click **Run workflow**.
4. Open the run and verify its cloud model, HTML verification and exact design-contract verification steps all succeeded.
5. Open the **Artifacts** section and download `devboard-cloud-design_cpu-[run id]`. Inspect `cloud-report.json`, `design-decision.json`, the frozen spec and `untrusted-design-proposal.html.txt`.

This does **not** create a GitHub Page, alter source, open/merge a PR or deploy. A manual Actions run is the only trigger. Hosted Actions usage may count against account quotas.

## The model's real, limited contribution

Qwen3 0.6B is invoked **on GitHub's ephemeral CPU runner** using Ollama, with one bounded loopback POST to `/api/chat`. It chooses exactly three enum values:

| Field | Choices | What changes |
| --- | --- | --- |
| `theme` | `aurora`, `arcade`, `slate` | Background, foreground, accent and CTA palette |
| `layout` | `stacked`, `split`, `cards` | Responsive layout and details panel placement |
| `focus` | `audit`, `clarity`, `handoff` | Which predefined heading and explanation appear in details |

That yields **27 distinct, measurable page configurations**. All text, CSS rules, colors and HTML tags are authored and allowlisted in repository code. **The model never writes HTML, CSS, scripts, arbitrary prose, commands, URLs, or files directly.** The frozen human-authored title, headline, description and button label always remain exact.

This is design **selection**, not autonomous coding. The `design-decision.json` artifact records the three model choices, fixed model identity, frozen spec digest and no-authority classification.

## Verification and evidence

The cloud runner executes:

1. A worker subprocess calls `qwen3:0.6b`, validates the exact three-field response and renders its choices through deterministic escaped HTML. Outputs are scratch-only, exclusive create.
2. An existing **separate R1-B parser/verifier subprocess** checks the resulting static HTML, spec SHA and byte SHA, script/external resource exclusions, navigation and semantic content.
3. A **second R1-G contract subprocess** revalidates the exact decision JSON, model identity and fully reconstructed allowed HTML bytes against the frozen spec.
4. A separate read-only final recheck starts fresh verifier subprocesses, rehashes the artifact and verifies decision/receipt bindings. Only when all checks pass can the cloud controller write the review-only exported artifacts.

The exported HTML file ends in `.html.txt`, so it is **not automatically hosted or rendered by GitHub**. Failed runs write `cloud-report.json` only, with bounded stage/reason codes and no leaked raw model output. `STATIC_REVIEW_READY_NOT_AUTHORIZED` does **not** authorize publication, repository modification or merging.

### Tests

GitHub CI uses a fake loopback Ollama server and **actual Python subprocesses**. It covers all 27 possible design choices, deterministic rendering, spec binding, exact SHA, malicious extra fields, invalid model choices, HTTP/JSON refusal, no-network precheck refusal, tampered decision or HTML and lack of release permissions. A passing CI suite still does **not** qualify a real cloud model interaction; that requires an actual manual `design_cpu` run.

The same security caveats as R1-F apply: the Ollama image/model download is not pinned or externally attested, processes share one GitHub-hosted OS account, and these are local-runner self-reports, not independent cryptographic attestation.

**Design goal:** Qwen makes a measurable choice; a fixed builder renders; independent static checks verify; a person decides. Ledger Above Ego.
