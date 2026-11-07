# Agentora Fleet R7: untrusted model suggestions to isolated code patches

**Status:** manually initiated, fixed-scope pilot, not an autonomous GitHub coding agent.

R7 accepts ONE proposal from local Ollama or externally generated public JSON,
checks it against a pinned source SHA and fixed allowlist, applies the candidate
to a disposable local Git branch, tests/builds in a network-disabled Docker
sandbox, and uploads the patch and evidence for review.

No source pushes, PR creations, merges, releases, deployments or credentials are
granted to the model or test runner.

## Strict first-pilot allowlist

- Public owner/repo: MichaelWave369/PhiMadaPrime, immutable ID 1443845098
- Branch: main, current exact 40-character SHA
- Sole editable file: src/reponerve.jsx
- Allowed change: exactly one unique text replacement
- Each old/new fragment: at most 1600 bytes and 20 line breaks
- Proposal: at most 8192 bytes; resulting patch: at most 12000 bytes
- Model-controlled fields: old_text, new_text, rationale

The trusted wrapper supplies repository identity, source SHA, file path,
original file hash, schema, and false authority flags. It rejects forged
permissions, extra fields, duplicate JSON keys, symlink targets, mismatched
hashes, dirty or wrong checkouts, ambiguous anchors, scope violations,
stale current HEAD and changed patches. Mechanical validation cannot rule
out semantically harmful code; manual review remains essential.

## Generate a proposal using local Ollama

Use a clean local clone of PhiMadaPrime at its current main SHA and a
working copy of Agentora with R7. With Ollama running locally:

    python scripts/fleet_r7_model_proposal.py preflight \
      --sha <CURRENT_PHI_MADA_MAIN_SHA> \
      --confirm REVIEW_PUBLIC_PHI_MADA_MODEL_PATCH \
      --output ./r7-preflight.json

    python scripts/fleet_r7_model_proposal.py suggest \
      --sha <CURRENT_PHI_MADA_MAIN_SHA> \
      --checkout ../PhiMadaPrime \
      --preflight ./r7-preflight.json \
      --model qwen2.5-coder:7b \
      --task "Clarify reservation snapshot timing in the RepoNerve view." \
      --output ./r7-public-proposal.json

The Ollama call uses a fixed loopback URL at 127.0.0.1:11434, never a
model-supplied URL, and sends only the one public source file and bounded
task. It does not modify code or transmit credentials. Invalid model JSON
or non-unique replacements are held. A separate model can produce the R7
JSON contract too; the declared model label is not verified provenance.

## Manual GitHub Actions candidate verification

After merging the R7 Agentora PR, select GitHub Actions >
Fleet R7 Public Model Proposal Candidate and supply:
- source_sha: the current PhiMadaPrime main SHA
- proposal_b64: base64 UTF-8 of the reviewed r7-public-proposal.json
- confirmation: REVIEW_PUBLIC_PHI_MADA_MODEL_PATCH

Generate proposal_b64 locally, e.g.:

    python -c "import base64,pathlib; print(base64.b64encode(pathlib.Path('r7-public-proposal.json').read_bytes()).decode('ascii'))"

NEVER include secrets, personal information, private repo names or non-public
source in the proposal. GitHub Actions inputs and short-lived artifacts
must be treated as publicly reviewable material.

The GitHub workflow does NOT call Ollama. It validates the proposal, checks
the current source HEAD before and after, creates one local-only candidate
branch, installs dependencies with lifecycle scripts disabled, and runs
fixed Node tests/build in a no-network, non-root, memory-limited Docker
sandbox. No checkout credentials are persisted, and the runner has only
contents:read permissions. It uploads preflight, proposal, candidate,
patch.diff, steps and final receipts for seven days.

## Limits of the receipt

FIXED_AUTOMATED_CHECKS_REPORTED_PASSED_AT_SHA means fixed automated exit
codes were zero, and the controller independently reconstructed the local
patch and rechecked the exact public HEAD. It is not a signed attestation,
independently reproduced test result, full product certification, approval
to merge, deployment, or authorization to change other repositories.

This first R7 path has no independent R3 lease attestation in GitHub's
remote runner. The broader multi-repository autonomous worker requires
versioned per-repo policy, source-bound leases enforced at action time,
independent code-review evidence, controlled branch-only PR creation,
and separate merge/release authority.
