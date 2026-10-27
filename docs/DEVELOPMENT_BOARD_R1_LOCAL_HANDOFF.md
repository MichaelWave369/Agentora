# Φ Development Board R1-A · Local GitPorch + PhiBot exact-commit handoff

**Status:** bounded, review-only pilot, building on merged R0. This is the first **read-only live local GitPorch adapter**, not a working autonomous builder/verifier pipeline. It cannot run models, build code, dispatch jobs, grant approvals, write GitHub, merge or deploy.

## New capability

1. Agentora operator explicitly enables and clicks **Read local GitPorch PhiRunners status**. It makes one GET to **127.0.0.1** only. It never starts GitPorch or its workers and never follows redirects. Disabled by default.
2. The operator enters a local GitPorch repo name, exact matching GitHub owner/repo, PR number, 40-character commit SHA, and a manually redacted JSON report from PhiBot's existing `steward:verify`.
3. Agentora checks that GitPorch's **latest retained** local Git-object-integrity job and Node built-in test job both report PASS for the same repo + SHA, and that GitPorch's overall/lane receipt health is complete.
4. Agentora separately checks that PhiBot's read-only `phibot.repo-verification.v1` export reports `CHECKS_PASS_REVIEW_ONLY` for the same GitHub repo, PR and SHA, with successful check evidence.
5. When both sides match, Agentora says **REVIEW_READY_NOT_AUTHORIZED**. Otherwise it says **HELD** with a specific refusal code.

**Neither result ever makes a PR eligible for merging.** Imported reports are caller-supplied, mutable and untrusted. The local PhiRunners data is checksum-checked, not authenticated or independently signed. A SHA match correlates content but does not prove independent identities, trustworthy tests, human consent, replay safety or current remote PR state.

## Windows field workflow

On the machine where GitPorch is installed:

```powershell
cd <your-local-GitPorch-clone>
npm.cmd start
```

In a second shell, inspect local runner state without executing a job:

```powershell
cd <your-local-GitPorch-clone>
npm.cmd run phirunners -- status
```

To generate real evidence for one **trusted disposable local Node repository**, follow the existing GitPorch docs `docs/PHIRUNNERS.md` and explicitly run **both**: (1) an integrity job and (2) a restricted Docker Node test job, on the **same exact commit SHA**. Loading Docker images and executing untrusted code are not safe default operations. Do not use production/private material for the pilot, and do not expose GitPorch ports on the LAN/WAN.

For PhiBot, run the already supported local `npm.cmd run steward:verify` in a separately authorized disposable GitHub repository after creating a **draft** candidate with an open eligible issue. Review the resulting JSON and copy **only redacted report data**, never a token, into the Agentora UI. See PhiBot `docs/REPO_STEWARD.md`; a read-only CI evidence report still does not grant merging.

Before launching Agentora **from the same Windows shell**:

```powershell
$env:AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED = '1'
# Optional only if GitPorch uses a nondefault port:
# $env:AGENTORA_DEVBOARD_GITPORCH_PORT = '3690'
```

Run Agentora normally, open **Development Board (R0)**, scroll to **R1-A Exact-commit evidence handoff**, click the local status read, enter the two explicit repository identities, PR and SHA, paste the **redacted** PhiBot JSON, then click **Compare exact-commit reports**. No data is saved to the DB by this feature; input remains in the Streamlit browser session. **Avoid remote-hosted Agentora access for this local-only workflow.**

To call the pure analysis API without local network access:

```text
POST /api/development-board/handoff/preview
{
  "local_repo": "Disposable",
  "github_repo": "MichaelWave369/Disposable",
  "pr_number": 7,
  "commit_sha": "<real SHA>",
  "gitporch": { ... PhiRunners status snapshot ... },
  "phibot": { ... PhiBot steward verify report ... }
}
```

Only supplied data is compared; the API never fetches local services or GitHub. Limit imported JSON to 128 KiB. Avoid sending unredacted reports, private paths or secrets.

## Hard negative controls

- Mismatched GitPorch or PhiBot commit SHA: **HELD**
- Git object integrity PASS without matching Node test PASS: **HELD**
- A newer failed or unfinished local run for the same repo + SHA: **HELD**
- GitPorch incomplete, unreadable or unrecognized lane: **HELD**
- PhiBot PR identity mismatch, stale head, failed/pending/truncated checks: **HELD**
- Fake `operator_approved`, `merge_grant` or report attestation fields: **still no permission**
- Missing local endpoint, unexpected port, redirects, invalid MIME or overlong response: **UNAVAILABLE**, never pretend success
- Only 20 recent GitPorch jobs are exposed by upstream status. Absence from that bounded display is **HELD**, not proof that no older run exists.

## Next independent gates

- Human-observed Code Brown test of R1 in Streamlit.
- Real Windows local GitPorch + PhiBot pilot receipts; CI cannot substitute for field observations.
- Identity/authentication and integrity checks for remotely obtained evidence, exact Git commit re-read, expiry/timestamp policy and signed provenance.
- Separate, sandboxed builder and verifier worker adapters, capability scoping and mandatory human permission for every write.
- Operator-granted draft PR creation in one disposable allowlisted repo. No autopromotion or auto-merging until independently qualified.

**Design rule: an agent's capacity to produce a passing-looking report never gives it authority to ship code.**
