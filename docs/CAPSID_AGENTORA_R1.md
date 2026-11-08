# ΦCAPSID × Agentora R1: locally fenced reference-context handoff

**Status:** implemented as a manual CLI bridge in Agentora. This is a
*point-in-time local context handoff*, not an automatic agent dispatcher.

The existing ΦCAPSID capability module lives in
[`MichaelWave369/PhiRepoNerve`](https://github.com/MichaelWave369/PhiRepoNerve).
Do **not** fork its HMAC, review, targeting or activation policy inside Agentora.

## Requirements

- A locally installed, reviewed PhiRepoNerve checkout that exports
  `phireponerve.capsid.eligible`, `CapsidStore.context`, and
  `phireponerve.review.ReviewStore`. Keep it pinned to a reviewed commit
  alongside Agentora; mismatched API versions must fail rather than downgrade.
- An existing, **active** locally HMAC-signed ΦCAPSID, staged and activated
  with the original local `phireponerve capsid` CLI.
- The exact **same** `PHICAPSID_HMAC_KEY` used for that capsule. Keep the key
  in your private secret manager or local session, never in a public file.
- Current ΦLoad knowledge pack plus its existing local review database.
- A locally current RepoNerve public steward record already ingested by
  Agentora, an R0.3 held source intake with exact source SHA, and a current R3
  local worker lease for the same repository and agent ID.
- A GitHub token sufficient for GET-only observations when applicable.
  The HEAD observer is scoped to the public MichaelWave369 repository
  identity and rejects renamed, private or archived repos.

## Workflow

Run both projects from a trusted local machine, using Python 3.12+:

```bash
python -m pip install -e ../PhiRepoNerve

# Follow PhiRepoNerve docs/CAPSID.md to:
# 1. review a ΦLoad pack,
# 2. compose/sign its capsule,
# 3. stage + activate it against your operator profile,
# 4. provision an Agentora R0.3 source intake and existing R3 lease.
# Existing source, steward, and lease workflows remain separate.

python scripts/capsid_context_handoff.py \
  --capsule /private/capsule.json \
  --profile /private/btm-agent.json \
  --intake /private/source-intake.json \
  --steward-db /private/fleet-stewards.sqlite3 \
  --lease-db /private/fleet-leases.sqlite3 \
  --lease-file /private/btm-steward.lease \
  --capsids-db /private/capsid.sqlite3 \
  --reviews-db /private/pack_reviews.sqlite3 \
  --confirm RELEASE_REVIEWED_CAPSID_REFERENCE_CONTEXT
```

The optional `--packs PATH` points at a local folder of reviewed ΦLoad packs.
If omitted, PhiRepoNerve's bundled curated packs are read.

**Do not publish stdout or pipe it straight into a trusted system prompt.**
It may contain task-specific reference content. A later authenticated agent
runtime must place the Welcome Charter in a trusted channel and the knowledge
data in a separately marked, low-trust reference channel. If installing the
provider or finding the private ledger fails, the script returns a `CAPSID_HELD`
error and exits nonzero. No implicit approval occurs.

## Checks made by the bridge

1. Validate the original ΦCAPSID envelope with its secret and current review
   ledger, exact pack digest, role, repository selector and required tags.
2. Require `reference.read` as the sole capability for this rung.
3. Confirm the capsule profile targets the **same** repository as the existing
   R0.3 source intake and exactly matches the current worker lease's label.
4. Check the existing R2 steward identity, R3 fenced lease generation, token,
   source SHA, repository numeric ID and remaining lease TTL.
5. Independently GET the exact GitHub public repository and its declared
   default-branch HEAD, rechecking the HEAD and lease through existing
   Agentora R0.5 logic.
6. Call the original PhiRepoNerve `CapsidStore.context()`, which rejects
   inactive capsules, unknown HMAC keys, changes to pack content, revoked
   approval or lost profile eligibility. Match the returned capsule digest
   and exact pack against the submitted envelope.
7. Repeat HEAD, steward, lease, and active capsule context observations
   before returning an advisory bundle, not authority.

This sequence narrows races at the **review instant**. It cannot prove that
HEAD, a lease or a pack review will remain stable after stdout is produced.

## Output boundary

The result's `reference_bundle` is a structured lower-trust knowledge payload
from the original PhiRepoNerve Chamber, with its application-authored Welcome
Charter. The outer envelope contains the current source SHA, repository ID,
lease generation and package fingerprints. The bridge does not export lease
tokens, local signing keys, private inventory or authenticated claims.

Every execution, dispatch, merge, deployment, agent identity and model-weight
change field is explicitly false. There is no automatic worker transport,
hosted API, Docker launch, model adaptation or CI workflow dispatch.

The HMAC key authenticates **holders of a local shared secret**. It cannot
establish independent publisher identity, and local agent labels do not
authenticate remote agents. The SQLite lease works only on one shared host;
it is not a distributed lock or a remote GitHub Actions runner credential.

## Verification and next rung

```bash
PYTHONPATH=.:server pytest -q server/tests/test_capsid_context_handoff.py
```

The offline CI test suite exercises the Agentora lease/HEAD checks with fake
GitHub responses and a faithful **mock of the ΦCAPSID provider interface**.
It does *not* establish a live end-to-end installation or remote worker delivery.
Perform a private local smoke test with actual, separately reviewed PhiRepoNerve
before relying on this bridge beyond advisory reference export.

**R2 proposal:** a purpose-built Agentora runtime adapter that authenticates
the receiving worker, enforces replay/expiry policy, and places knowledge
separately from privileged instructions. Keep real tool installations and
model-weight adaptation in later, separately scoped, canary-tested rungs.
