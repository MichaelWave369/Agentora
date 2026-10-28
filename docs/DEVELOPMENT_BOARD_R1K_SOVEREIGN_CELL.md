# Φ Development Board R1-K · Sovereign Cell Contract Pilot

**Review-only · No agent execution · No repository writes · No sovereignty certification**

This pilot makes an architectural vocabulary machine-inspectable. It is informed by two operator-supplied PHI369 architecture documents, including a v1.0 specification of **3 maturity tiers, 9 organs and 9 operational principles**. **The source documents are not included** because the later document has a confidentiality marking and historical ecosystem inventory. This pilot is an independently authored, scoped implementation, not publication of those documents.

## What R1-K actually checks

A single, stdlib-readable JSON manifest lives at `examples/development-board/sovereign-cell.json`. JSON was chosen rather than a YAML dependency to keep the current review path **deterministic and zero-dependency**; this does not prohibit future YAML manifests.

**Three declared tiers, not certification levels:**

| Tier | Organs | What declaring them means |
| --- | --- | --- |
| Being (3) | Face, Mind, Memory | UI, bounded logic and review-evidence handling are *described*. |
| Function (6) | + Hands, Body, Shield | Explicit adapters, runtime and policies are *described*. |
| Sovereignty (9) | + Pulse, Continuity, Seed | Observability, recovery and reproducibility are *described*, **not independently proven**. |

Nine required operational principles are `one_module`, `one_manifest`, `one_runtime`, `one_recovery_path`, `local_first`, `observable_by_default`, `secure_by_default`, `easy_to_inspect`, and `easy_to_restore`. Each requires a short explicit assessment of `PARTIAL`, `NOT_DEMONSTRATED`, or `EVIDENCED_CLAIM_ONLY`.

The **current real Development Board** is intentionally declared as **mixed local and manually dispatched GitHub Actions**, with separate subprocess builder/verifier boundaries. It is not represented as one fully local runtime. In particular, `one_runtime`, `one_recovery_path` and `easy_to_restore` must currently be `NOT_DEMONSTRATED`. Even when all nine organ paths exist, `readiness` is always `NOT_SOVEREIGN_QUALIFIED`.

Each organ cites one or more **existing repository files**. The validator checks strict field sets, path allowlists, exact repository file existence, symlink refusal, path component traversal refusal, bounded file sizes, and SHA-256 of the actual files at the checked-out GitHub Actions commit. This demonstrates **internal source-file consistency**, not that the referenced feature operates correctly or is secure. A second readback recomputes the receipt before exporting it.

No Phi ratio, `0.809` threshold, numerical covenant, formula, historical agent identity, or "fail open" phrase is allowed to function as a security gate. **Availability may degrade gracefully; authorization must fail closed.** The raw source documents' brand names, historical deploy claims and private inventories are intentionally not published or adopted as current fact.

## Browser-only trial

After R1-K's PR is merged:

1. Open [Agentora R1-K Sovereign Cell Contract](https://github.com/MichaelWave369/Agentora/actions/workflows/development-board-sovereign-cell.yml).
2. Select **Run workflow** on `main`. No input, secret, model download or local installation is needed.
3. Open the completed run's `agentora-r1k-cell-review-...` artifact and inspect `sovereign-cell-review.json`.
4. Expect `NINE_ORGANS_DECLARED_REVIEW_ONLY`, `organs_declared: 9`, `principles_checked: 9`, `readiness: NOT_SOVEREIGN_QUALIFIED` and `eligible_for_merge: false`.

This workflow uses `contents: read`, no persisted checkout credentials and **manual dispatch only**. It does not invoke models, fetch arbitrary URLs, open issues, propose edits, change GitHub source, deploy, approve or merge.

## Known limitations and next build goals

- **Not a compliance or operational attestation.** Tests and repo-file hashes do not demonstrate restoration, data portability, cryptographic provenance, process confinement or independent audit.
- **Read-only manifest schema pilot.** The single JSON file is currently scoped to Agentora's Development Board capability, not every repository or every service.
- **No autonomous recovery.** A cell must eventually prove it can export, restore and replay state *from its own artifact*; merely listing a recovery file isn't enough.
- **No false maturity promotion.** Tier 9 is an anatomical declaration; qualifying it will require real restore drills, source isolation, run evidence, policy enforcement and human review.
- **CI and manual trial are separate gates.** The GitHub PR's `pytest` suite exercises real on-repo evidence and negative cases, but first real `workflow_dispatch` is the distinct field qualification.

### Logical R1-L target

Design a **portable read-only cell seed/receipt bundle** with a documented one-command restore/replay *test on disposable state*, never on user data or production credentials. Verify checksums, replay and failure handling before considering any broader cell registration.

**Ledger Above Ego. Declaration is not evidence; evidence is not authorization.**
