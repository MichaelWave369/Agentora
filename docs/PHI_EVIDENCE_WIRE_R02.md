# Φ Evidence Wire R0.2 · GitHub-side corroboration

**Candidate; must pass PR CI and a real source-backed field trial.**
R0.2 extends the merged R0.1 adapter. It consumes the existing GMED v1
report and R14 Issue journal record, then independently checks a live GitHub
PR and its exact merged SHA. No new repo or orchestrator.

## What R0.2 actually rechecks

1. The GitHub PR exists, reports merged=true, targets the expected **public**
   repository's current default branch, and its **merged commit SHA** equals
   the supplied exact SHA.
2. The target default branch is **still at that SHA** before and after the
   inspection. A later commit is a HOLD. This intentionally narrows R0.2 to
   snapshots where the GMED merge SHA and the R14 audited source SHA are one
   and the same commit.
3. GitHub check-runs (latest filter) and legacy statuses are fetched
   directly, with bounded complete pagination and no silent omission. Their
   outcomes and full observed list must match GMED's declared rows. A skipped
   or neutral result is not sufficient alone.
4. The **original Agentora R14 journal comment** must exist on the specified
   Mission Issue and match the supplied JSON record exactly. The comment
   must be attributed by GitHub to `github-actions[bot]` and be unedited.
5. An optional PhiStream CLAVIS **public research summary** can accompany
   the report without ever contributing to security approval.

The network client is stdlib-only, read-only, pinned to
`https://api.github.com`, refuses redirects, uses strict size/time/
pagination limits and fails closed on errors, changed sources or missing
evidence. It supports an optional `GITHUB_TOKEN` environment variable for
rate-limit handling; no token is printed or recorded in output. For public
repositories, a token is not required.

## One-shot usage

You need a **real** R14 journal record linked to an Agentora Fleet Mission,
and the **same source SHA** must have been the merged commit of a real target
PR verified by GMED. The original R14 journal comment's inner JSON object
is the `--r14` input. Do not use an augmented workflow response containing
extra `comment_id` or browser URLs. This strict binding is intentional.

```bash
python scripts/phi_evidence_live.py \
  --repo MichaelWave369/PhiMadaPrime \
  --pr <actual-pr-number> \
  --sha <real-40-character-merged-and-current-default-SHA> \
  --gmed /path/to/gmed-report.json \
  --r14 /path/to/r14-original-journal-entry.json
```

The placeholders are not executable. Optional `--clavis` points only at a
sanitized research summary (never private datasets, blind answer keys, model
responses or internal memory). On successful live reconciliation, the program
prints one `agentora.phi.evidence-live.v0.2` JSON receipt with state
`GITHUB_METADATA_CORROBORATED_REVIEW_ONLY`. A HOLD exits with code 2.

**Important:** The current Fleet R14 pilot relates to a specific source
snapshot for PhiMadaPrime; do not assume it coincides with a GMED-qualified
merge commit. If no matching PR/source pair exists, HOLD is the correct
result, not a reason to forge or relax evidence.

## Explicit limitations

- This is a **fresh GitHub API re-observation** of GitHub-owned metadata,
  not an independent host, a proof of repository ownership or cryptographic
  attestation of the data source.
- The existence of the R14 journal comment does **not** revalidate its
  underlying R13 audit/QA ZIP bytes, their provenance, or the *current*
  contents of expiring GitHub artifacts. R14 originally performed those
  checks; R0.2 does not claim to redo them.
- GitHub check-run success is not a proof that software is secure, nor does
  R0.2 independently read enforced branch rulesets / required check policy.
- There is **no mathematical theorem-prover**, no compiled-code proof,
  no attestation of a model checkpoint or silicon cognition, and no
  independently completed human QA.
- Every output explicitly denies permission to dispatch, write code, merge,
  deploy, or promote model routing.

## Qualification gates

```bash
python -m unittest server.tests.test_phi_evidence_live -v
python -m unittest server.tests.test_phi_evidence_wire -v
```

Agentora's existing CI pytest job also discovers both
`server/tests/test_phi_evidence_live.py` and
`server/tests/test_phi_evidence_wire.py`. Regression fixtures test
changed branches, forged PR merges, omitted/extra/failing/pending checks,
wrong check SHA, incomplete pagination, legacy status failure, edited
journal comments, non-bot comments and authority escalation.

**R0.3** is a separate design and review: a formally specified software
property, a real proof checker operating on pinned spec and implementation,
and replayable proof artifacts. Never upgrade an R0.2 metadata observation
into a mathematical proof or a generic autonomous merge permission.

**GMED = Gerged + Mreened + Evidence Documented.**
