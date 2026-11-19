# Agentora R9 → Autonomous Turn R1

R9 can queue one exact-source documentation edit for public Agentora, pass it
to the existing hosted R1 workflow, and reconcile the result. One RepoNerve
event admits one mission. GitHub's original protected-environment review is
the authorization for each turn. The local queue, its replay fence and issue
intake carry no merge authority.

## Hosted without installing Agentora

Owners who do not run local Agentora or RepoNerve on their PC can inspect the
[GitHub-hosted docs dispatch pilot](FLEET_R10_HOSTED_DISPATCH.md). It schedules
one bounded, owner-authored public docs task at a time through the **existing
Autonomous R1** approval and merge workflow, using a GitHub issue fence and
GitHub's built-in Actions credentials. No local software or personal token is
needed for this narrow hosted transport.

**This is not the full R9 migration:** the canonical SQLite queue, fleet
mission scheduling, RepoNerve event ingestion and product release workflows
have **not** yet been ported to durable hosted storage. The local procedures
below continue to describe the existing R9 lane, not a required installation
for owners using the hosted pilot.

## One-time setup

1. Have the queue and cockpit PRs reviewed and merged through normal GitHub
   review. Keep the existing Agentora Safe Auto Merge ruleset and R1 owner and
   publisher configuration described in [Autonomous Turn R1](AUTONOMOUS_TURN_R1.md).
2. Run PhiRepoNerve's normal public scan/watch and loopback `serve` on port
   8765. Both the steward registry and queue use the existing Agentora SQLite
   paths under `~/.agentora/`. Keep the service on the same host and user.
3. From MichaelWave369, create an expiring fine-grained GitHub PAT restricted
   to **Agentora** with repository **Actions: Read and write**. Supply it to
   the local Agentora process as `AGENTORA_R1_DISPATCH_TOKEN`. The controller
   checks the authenticated owner's numeric ID, the live repository and
   branch, the current ruleset and the owner environment before dispatch.
   It submits only `autonomous-turn-r1.yml` on main. The owner token is separate
   from the publisher App, and never reaches the worker, PhiMada, or GitHub
   workflow inputs.
4. Set `AGENTORA_R1_READ_TOKEN` for the local observer with only the Agentora
   repository read permissions needed for Actions, Contents, Pull requests
   and Checks. Artifact ZIP downloads need authenticated Actions read. R1's
   existing owner-only environment and App key stay on GitHub.
5. Run the existing R9 watcher on that host under its service manager, using
   the reviewed checkout and configured environment. It takes one tick per
   minute by default and restarts from the same SQLite paths. Deploy either
   the watcher or an OS-scheduled one-shot `tick` on that host. Run the cockpit
   locally on loopback to see the snapshot without importing it each time.
   Save the snapshot under the PhiMada checkout's ignored development path.

   ```bash
   python scripts/fleet_r10_r1.py watch --dispatch \
     --snapshot /path/to/PhiMadaPrime/public/fleet/r9-turns.json
   ```

   Start PhiMada with `npm run dev -- --host 127.0.0.1`, then open Mission
   Board. Alternatively, import a redacted snapshot from the R9 adapter
   into the Mission Board's queue panel. The browser performs GETs to verify
   linked GitHub results. It receives no credentials, task text or edits.

   An observation-only smoke run uses `watch --cycles 2` without
   `--dispatch`. An active watcher requires both credentials at startup.
   Missing credentials leave queued missions intact. Three consecutive
   failed cycles exit with status 3 and emit a bounded reason for the
   service manager. A restart reloads the same mission and submission fence.

## Submit the next turn

1. Refresh the public RepoNerve scan and a clean Agentora main checkout.
   Use `python scripts/export_phireponerve_public.py --output /tmp/observed.json`
   to find an eligible Agentora event ID in `recent_events`. R9 accepts
   current visible `first_observed`, `visible_again` and
   `push_activity_observed` events and rejects replays or stale bytes.
   A large scan can fill the newest 200-event page. Use
   `--event-offset 200` on the export command to select the next page.
   Ingest one chosen projection per scan ID so the source digest stays stable.
2. Prepare a task locally from a clean exact-main checkout. The **before**
   text must be unique in an existing allowed docs file. The worker applies
   one literal change and runs the fixed docs check. Choose a new task ID
   per turn and store the task outside the checkout.

   ```bash
   python scripts/fleet_r10_r1.py prepare --source /path/to/clean/Agentora \
     --task-id r1-docs-next-unique --path docs/EXISTING.md \
     --before 'Exact original text' --after 'Reviewed replacement text' \
     --objective 'State the scoped objective' --acceptance 'State what to inspect' \
     --out /tmp/r1-task.json
   python scripts/fleet_r10_r1.py enqueue --task /tmp/r1-task.json \
     --observations /tmp/observed.json --event-id EVENT_ID \
     --confirm QUEUE_AGENTORA_R1_DOCS
   ```

   Omit `--observations` to read the public projection from the running
   local RepoNerve API. Admission validates the immutable source and edit.
3. Open the Actions run linked in the cockpit and inspect the frozen
   `autonomous-task-RUN_ID` artifact. In **Review deployments**, approve
   `autonomous-turn-owner` with exactly `APPROVE <task-sha256>` before its
   four-hour expiry. Submit future tasks only after the current mission has
   merged or its hold has been reconciled. Use a new current source and a new
   observation event for each turn.
4. The existing R1 jobs handle the isolated edit, App-published branch and
   PR, exact SHA push and pull-request CI, and ruleset-gated squash merge.
   The queue independently re-reads the App PR identity, the whole tree and
   changed file, both CI event types, the owner review, and the merge commit.
   The cockpit can separately verify the result check on the same PR head.
   A docs merge still leaves deployment and product acceptance outstanding.

## Holds and recovery

The local database persists the frozen task and event digest, one-shot
submission fence, run and PR IDs, exact CI and merge evidence, and one hold
reason per mission. It serializes admission and submission with R9's existing
fair selection and one-unresolved-mission-per-repository rule. A local slot
reserves dispatch. The hosted GitHub job owns the execution lifecycle.

A lost dispatch response permits up to three bounded read-only searches,
spaced at least one minute apart, for a successful original plan containing
the exact task. The private ledger spends a read slot even if a process
crashes during the lookup. A new POST is never used to resolve an unknown
result. A later operator can attach a known original run via
`attach --mission-id MISSION --run-id RUN_ID`. This also supports manual
owner issue intake when Actions write is unavailable. It verifies GitHub's
artifact ZIP digest and exact frozen task before binding any run ID. A hold
from before any submission can use `retry-preflight --mission-id MISSION`
after the named local configuration is repaired. It still requires a fresh
task and an unused submission fence.

A late-CI hold retains the PR and its exact head. R9 may observe the result
again, but has no permission to re-run, approve, label or merge. If appropriate,
use the [existing separate R1 recovery approval](AUTONOMOUS_TURN_R11_LATE_CI_RECOVERY.md)
and retain its evidence. R9's current terminal merge qualification is scoped
to the original R1 merge job. After hold reconciliation, use R9's existing
`archive-held` command to clear the unresolved slot. An unconfirmed live
submission cannot be archived before its task window ends.

After two real sequential docs merges through one queue, explicitly select
a second public repository, qualify its repository ID, source/CI checks,
scope and separate publisher installation, and repeat the same evidence
criteria. RepoNerve's public census is observation. Deployment and distribution
are admitted separately using PhiOS's and Trellis's own package review.
