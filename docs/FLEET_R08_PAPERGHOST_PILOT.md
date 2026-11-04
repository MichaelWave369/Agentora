# Fleet R0.8 · First independent second-project sandbox pilot: PaperGhost

## Why PaperGhost?

PhiMada Prime's **One Repo · Finish Lane** can export an exact-SHA verification request, and its R27 return panel can correlate the original request with the *offline* Agentora R0.3 receipt. R0.3 **does not execute tests**. Agentora R0.6 executes tests only on a fixed PhiMadaPrime pilot.

This rung extends **real bounded check execution** to a *second* known public repo, [MichaelWave369/PaperGhost](https://github.com/MichaelWave369/PaperGhost), not a generic arbitrary-repository executor. PaperGhost is a React/TypeScript/Vite reader PWA. Its existing commands are `npm test` (Vitest) and `npm run build` (TypeScript `tsc -b` and Vite build).

**This is an operator-run test pilot, not an autonomous project finisher.** It does not ingest, interpret or execute arbitrary user-requested commands, nor turn a R0.3 intake acknowledgment into execution permission.

## Operator steps after merge

1. Select PaperGhost in [PhiMada Prime](https://michaelwave369.github.io/PhiMadaPrime/) Mission Board → One Repo · Finish Lane. Check GitHub HEAD, scope its *web_app* completion contract and download an exact-SHA request if eligible. Optionally process that file through Agentora's separate offline R0.3 intake. Those steps do not trigger R0.8.
2. In GitHub, determine PaperGhost's current exact 40-character **`main` HEAD**. It may change after this documentation was written.
3. Open [Fleet R0.8 PaperGhost Sandboxed Acceptance Pilot](https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r08-paperghost-pilot.yml) in the **Agentora repository**, select `main`, and click **Run workflow**.
4. Set `source_sha` to PaperGhost's exact current 40-character HEAD, and type **`RUN_PAPERGHOST_TESTS`** into `confirmation`. This is scoped approval of the fixed install/test/build run only, not approval to merge.
5. The R0.8 trusted source guard fetches the expected public GitHub repository by **numeric id `1443390000`**, owner, canonical name, nonprivate/nonarchived/default-branch `main`, and compares two HEAD observations to the requested SHA before any checkout.
6. Checkout runs with credentials disabled and `submodules:false`, `lfs:false`, `fetch-depth:1`; exact checkout commit is compared with the operator-supplied SHA. On the host, `npm install --ignore-scripts --no-audit --no-fund` prepares dependencies. No application or workflow source lifecycle scripts run in this step.
7. Two **fixed commands** execute separately in network-disabled, read-only-root Docker sandboxes, each with UID 1000, no capabilities/new privileges, CPU/RAM/PID bounds and a five-minute timeout. The only commands are `npm test` and `npm run build`. They cannot receive the Actions token, home workspace, Docker socket or additional secrets.
8. The trusted host records the actual install/test/build exit codes and re-reads PaperGhost HEAD **twice after testing**. Any changed source or missing/failed fixed checks holds or fails the workflow. On success, the result is exactly `AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA`, not a product acceptance certificate.
9. Download `fleet-r08-paperghost-<run-id>` from the *manual run's* GitHub Actions artifacts. It contains small `preflight.json`, `steps.json`, `final.json` only (7-day retention), as **reported** fixed-run evidence. The workflow does not upload source files, private libraries, test logs or user documents.

## Important acceptance limits

- The provided `source_sha` is a manually typed immutable commit; R0.8 is **not currently bound to the SHA-256 of an R8 request/Agentora R0.3 receipt**. The exact SHA link is visible and should be reconciled by the operator. No claim of a completed R0.3→R0.8 acceptance chain is made.
- R0.8 tests the **source** at its exact SHA in an isolated environment; it does not perform an interactive browser test, deployed-Pages acceptance, accessibility audit, privacy/security audit, offline-PWA user journey or real human user acceptance.
- PaperGhost has no committed `package-lock.json` at this point. Dependency install uses package semver ranges, which are **not reproducible or supply-chain attested**. The Docker Node image is tag-based, not digest-pinned. Its output is **not a signed artifact attestation**.
- Running `npm run build` includes TypeScript compilation, but it is **not a separate independent typecheck evidence receipt**.
- The sandbox runs code specified in PaperGhost's package scripts, but only **inside a resource-bounded, network-disabled container**. The host does not execute those scripts.
- A green workflow records the host's observed exit codes and source identity only. It does **not** complete the project's verification contract or authorize deployment/merges.
- This R0.8 pilot is **manual-only**, with no scheduled or PR-triggered executions. There is no arbitrary repository, command, workflow, token, network endpoint or output path input.
- There is no independent R0.9 GitHub ZIP reviewer or PhiMada PaperGhost evidence importer yet. That is the natural next rung after an actual R0.8 pilot, not something we should claim exists.

## Code and CI

- `scripts/fleet_r08_paperghost_pilot.py`: separate source verification and host-recorded final receipt, cloned from the trusted R0.6 pattern with fixed PaperGhost ID, manual confirmation and unique R0.8 schemas.
- `.github/workflows/fleet-r08-paperghost-pilot.yml`: operator-triggered GitHub Actions pilot. Permissions: `contents: read`; credentials are never persisted. Artifacts are 7-day-retained metadata receipts.
- `server/tests/test_fleet_r08_paperghost_pilot.py`: source identity, malformed SHA, forgery, head drift, tested command bounds and non-authority regression checks.
- Agentora standard Python 3.12/3.13 CI runs the new tests. **Passing PR CI does not trigger the manual PaperGhost pilot.**

**Operator scope is one approved fixed checkout and two fixed checks. Further independent artifact verification and release decisions remain separate.**
