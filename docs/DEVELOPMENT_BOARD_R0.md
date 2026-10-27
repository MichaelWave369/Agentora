# Φ Development Board R0: nine-skill, review-only pilot

**Current scope:** An original, local-first planning and evidence-inspection surface inside Agentora. The nine-role catalog, receipt contract, API and Streamlit board are implemented. **This does not execute coding agents, run tests, verify GitHub, grant rights, merge, deploy, or store approved specs.**

## What R0 provides

- `Development Board (R0)` in the existing Streamlit navigation.
- A declarative nine-role skill catalog at `server/app/services/development_board/skill_catalog.json`.
- Three endpoints: `GET /api/development-board/skills`, `GET /api/development-board/demo`, and `POST /api/development-board/evaluate` (pure receipt shape/consistency checking only).
- One explicitly synthetic example containing a fake SHA, fake verifier, fake approval and fake evidence reference. Its result is **never merge-eligible**, even if shape checks pass.
- One optional **session-only user-authored draft**. It is not persisted to SQLite, synced, executed, or transmitted to third parties.
- Negative controls demonstrating stale commit/spec checks, independent actor identity, approval claims, fake provenance, and absence of evidence.

**Historical source limitation:** the nine stable historical `legacy_id` values are preserved from the supplied design handoff, but historical skill source files have not been recovered/imported. Catalog `source_status` is `DESIGN_RECOVERED_NOT_SOURCE_IMPORTED`. Display labels and responsibilities are initial mappings, not evidence of original skill behavior.

## The nine roles

**3 → 6 → 9:** Master Spec Builder specifies, Implementation Forge builds, Wayne Rider Proving Ground independently tests the exact submitted SHA. The human operator makes the release decision. Drift Compass, Horizon Roadmap, Wave Rider Possibility Loom, Constellation Chamber, Field Bridge, and Arc Rider Continuity Ark provide advisory review, planning, integration and continuity.

Role labels and skill routing **never** imply tool permissions.

## R0 trust boundaries

1. The API has no GitHub client, repository filesystem writes, worker dispatch, external provider access or merge endpoint.
2. Receipt strings, SHA digests, JSON evidence and approval booleans are **untrusted caller-provided claims**; exact-text agreement is not an independent verification or signature.
3. A structurally valid claimed receipt is marked `UNVERIFIED`, with `eligible_for_merge=false`. Bad structure is `REJECTED`. Either way, R0 cannot approve anything.
4. An independently generated code commit must invalidate any verdict attached to a previous commit; any spec change invalidates previous proof.
5. The user must separately authorize real repository writes and merges in the future. No auto-merge.
6. Public sample data is fictional and contains no live credentials, prompts or private source.

## Run the relevant tests

```bash
python -m pip install -r requirements.txt
AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=server pytest -q server/tests/test_development_board.py
```

Normal repository CI also runs the full server test suite on Python 3.12/3.13 and builds the web application. Passing CI proves the tested R0 contracts, **not** local Ollama, GitPorch, PhiBot, PhiOS or agent dispatch.

## R0 Code Brown human usability check

Have a real person unfamiliar with the system test the current Streamlit page on their actual device and record observed results, without helping until the attempt ends. Each item is a **human-observed** check rather than a synthetic CI certification:

1. Can they explain in five seconds that the board is only a prototype?
2. Can they locate the Development Board from navigation?
3. Can they create a named local draft with acceptance criteria within 30 seconds?
4. Can they find the nine roles and distinguish builder from verifier on their device?
5. Can they recognize the fake demo evidence and tell why it cannot authorize merging?
6. Can they recover from an empty submission and describe what to do next?

Record device, tester consent, observation timestamp, each outcome, confusion points, and necessary changes. **Not tested with a person until a separate field report exists.**

## R1 adapter contracts to design, not yet implemented

- **Agentora → Coordinator:** scoped repo identifier, operator-authored spec + digest, role assignments, bounded work item IDs, explicit operator grants, retry budget, lifecycle events.
- **Coordinator → GitPorch:** isolated repo workspace with base/head SHA, read-only git integrity and restricted test evidence; no default LAN/WAN exposure.
- **Coordinator → PhiBot:** allowlisted drafting/repair with independent verifier actor, exact verified SHA/spec digest, immutable receipt reference; never accept an agent's PASS as sufficient.
- **Coordinator → PhiOS / Vessie:** request a narrowly-scoped authorization; keep observation separate from authority; preserve operator decision, signed proof (only when verified), audit and rollback metadata.
- **R1 proof states:** `PROPOSED → SPEC_DRAFT → AWAITING_SPEC_APPROVAL → READY → CLAIMED → SUBMITTED → UNDER_REVIEW → HUMAN_REVIEW`. Failure returns to `READY` with reason; neither automated reviewer nor CI can transition to MERGED.
- **First allowed pilot:** one explicitly selected non-production public repository, one bounded task, separate builder and verifier, no merging. Prove replay/recovery and stale-proof rejection before enabling real writes.

These adapters remain proposals until built and independently field-qualified.

## Attribution

Inspired by general spec-driven autonomous development patterns, including Pullboard, without copying its source, UI, branding or licenses. The actual Agentora implementation is original.
