# Agentora R3: bounded local-model patch pilot

**Status: implementation candidate; no hosted autonomous coding is claimed.**
This is an opt-in local Ollama proposal experiment for one existing low-risk
React component. The model proposes actual replacement source code, instead of
R1's deterministic literal substitution. The output is **not** a GitHub PR,
not an authorization, not a production qualification, and never auto-merges.

It retains R1/R2's operating rule: a model cannot choose paths, tests, review
policy, CI or permissions. A code change needs independent human review on the
exact PR commit if a later rung connects it to the existing publisher.

## How to try the pilot on Windows

Requirements: Python 3.12+, Git, npm/Node, Docker Desktop with Linux containers,
and Ollama running locally with an already installed coding model. The default
is `qwen2.5-coder:7b`. This pilot never downloads a model.
You can replace `--model` with another installed model's local name.
Node/npm resolves the existing trusted lockfile with lifecycle scripts disabled;
Docker pulls the Node build image if it is not present. Normal registry/image
network use is separate from the untrusted code build, which runs without network.

Do this in a *clean* Agentora checkout after the infrastructure PR is merged.
The frozen task spec must be created **outside** the repository checkout so
`git status` stays clean. From PowerShell:

```powershell
cd <your-Agentora-checkout>
git pull --ff-only
ollama list

$spec = Join-Path $env:TEMP 'agentora-r3-template-gallery.json'

python scripts/autonomous_r3_local_patch.py init $spec --source . --target-path web/src/components/TemplateGallery.tsx --task-id r3-local-template-gallery --instruction "Improve keyboard and screen-reader accessibility in the TemplateGallery component without changing routing, dependencies, or other files."

python scripts/autonomous_r3_local_patch.py plan $spec --source .
```

The `plan` command is read-only. It displays a
`frozen_spec_digest` that binds the task, exact Git
commit, original file SHA-256, file allowlist and patch budget.
Read the entire JSON spec and review its instruction. **Do not approve a digest
you have not inspected.**

Then paste that digest, verbatim, into the following command:

```powershell
python scripts/autonomous_r3_local_patch.py run $spec --source . --model qwen2.5-coder:7b --approve-spec-digest <paste-digest-here> --i-approve-local-model
```

The explicit approval is a local operator acknowledgement, **not**
cryptographically authenticated remote authorization. The runner rechecks
the clean source SHA and original file bytes immediately before inference.
Only afterward does it POST to 127.0.0.1:11434/api/chat. The model returns a
JSON object containing an entire proposed file and short summary.

The runner rejects changed paths, extra JSON fields, unchanged files, oversized
diffs, invalid encoding, changed source bytes and non-allowlisted files.
It copies the checked-out source to a disposable workspace outside the repo,
writes only the approved component path, installs dependencies with
`--ignore-scripts`, and runs the frontend build using
R1's fixed **no-network, read-only-root, nonroot Docker** sandbox.
The source checkout and GitHub repository are never mutated.

On success, the workspace contains:

- `frozen-task.json`: approved task snapshot
- `candidate/web/src/components/TemplateGallery.tsx`: untrusted model proposal
- `proposal-receipt.json`: current source/task SHA, file
  before/after hash, exact diff hash, tested build result and
  `REVIEW_READY_NOT_AUTHORIZED` status

**Read the diff and review the generated code before attempting anything else.**
A passing build alone does not prove accessibility, software correctness,
security or field acceptance. Never blindly run a generated candidate with
developer credentials. The model and Python processes still share the local
user account; only the build of the candidate runs inside the Docker isolation
boundary. A Docker container is not a hardened hostile-kernel proof.

## Exact capabilities and boundaries

| Stage | What happens | Authority |
|---|---|---|
| Init | Freeze one allowlisted file's source SHA and task | Local file creation only |
| Plan | Verify clean checkout and present digest | No model, Docker or writes |
| Propose | Local Ollama returns full revised React component as untrusted JSON | No GitHub/token access |
| Constrain | Validate single file and bounded diff | Refuse broad output |
| Test | Build in R1's no-network Docker recipe | Local, credential-free result |
| Receipt | Store immutable hashes and status for inspection | `eligible_for_merge=false` |
| Publish/merge | **Not implemented in this pilot** | None |

The target allowlist is reused from R2: Nav.tsx or TemplateGallery.tsx.
No scripts, workflow files, dependencies, configuration, authentication,
server code, or PR permissions are included. No automatic retries or "make
the tests green" loop is granted. Proposals may be unusable and are never
promoted without a subsequent explicit human-controlled GitHub mechanism.

## Verify before field use

Run the new synthetic tests plus the existing R1 vertical-slice tests:

```powershell
$env:PYTHONPATH = 'server'
python -m pytest -q server/tests/test_autonomous_r3_local_patch.py server/tests/test_autonomous_turn_r1.py
```

CI uses mock model responses and fake Docker command execution for the R3
unit tests. It does **not** connect to your actual Ollama instance or
field-qualify a generated patch. CI separately runs the actual normal Agentora
backend/frontend checks, not the R3-generated candidate.

## Next rung after local field proof

1. Verify an actual local Ollama candidate and capture a redacted receipt.
2. Add an independently verifying intake of the proposed artifact to a
   **separate draft-PR** publisher. The authenticated owner must approve
   source SHA, exact patch SHA, permitted path and test plan before a write.
3. Have the trusted publisher reproduce the exact candidate bytes, check full
   Git tree and compare live required CI on the resulting immutable commit.
4. Keep R2 exact-head independent collaborator review and trusted merge policy.
   No model-originated label, self-review, API token or branch-protection bypass.
5. Qualify the full loop with a hosted, independently observed real PR before
   claiming "AI writes and merges code autonomously."

**Ledger Above Ego: proposal ≠ verification ≠ authority ≠ merge.**
