# Phi Independence R05-A — offline, reviewed patch test

Experimental. Reuses existing autonomous R3 task, source, diff and tracked-archive
functions. Does not depend on R04-B being merged. No model call or automatic patch
generation in this rung: the operator supplies one complete UTF-8 replacement file.
Only existing R3 allowlisted Agentora UI components, no broad repo execution.

## Preparation (while connected, separately authorized)

Use a clean trusted Agentora checkout, local Docker Desktop Linux containers or
Linux Docker, a trusted local Node 22 image, and a dedicated npm cache containing
only public dependencies for this exact lockfile and Linux architecture. Populate
the cache using a trusted dependency-install procedure with lifecycle scripts
disabled. Do not supply a normal home-directory cache, private registry data,
tokens, credentials or personal files. Cache preparation is not automated here.
Inspect local image ID with `docker image inspect node:22-bookworm-slim --format '{{.Id}}'`.
Use the exact sha256 image ID; never a mutable tag. Do not trust an image merely
because it has a digest. Build input and image must be independently trusted.

## Plan and approve

Use a private existing directory outside the checkout. Create a frozen R3 spec
with its existing init command; place a reviewed candidate replacement file in the
private directory. Example PowerShell, substituting actual paths and image ID:

```powershell
python scripts/autonomous_r3_local_patch.py init D:/PhiVault/forge-task.json --source . --target-path web/src/components/Nav.tsx --task-id forge-nav-access --instruction "Improve the navigation accessibility label."
python scripts/phi_forge_r05a.py plan D:/PhiVault/forge-task.json --source . --replacement D:/PhiVault/Nav.tsx --image-id YOUR_SHA256_IMAGE_ID --cache D:/PhiVault/public-npm-cache
```

Review the entire plan, task and diff, and full replacement. Independently block
external network access and then pass the exact plan digest:

```powershell
python scripts/phi_forge_r05a.py test D:/PhiVault/forge-task.json --source . --replacement D:/PhiVault/Nav.tsx --image-id YOUR_SHA256_IMAGE_ID --cache D:/PhiVault/public-npm-cache --approve-digest YOUR_PLAN_SHA256 --confirm-offline
```

One fixed Docker invocation uses explicit default local daemon socket/pipe,
an empty temporary Docker config, --pull=never, --network none, read-only root,
nonroot user, resource caps and read-only source/cache mounts. Inside the cage,
copy both mounts to bounded tmpfs, install using npm ci --offline --ignore-scripts,
then npm run build. No host npm, automatic image pull, GitHub action or publishing.
The original checkout is untouched; candidate temporary files are normally removed.
Build output is suppressed to avoid spilling private content. Nonzero exit is HELD;
stdout receipt binds exact patch, task/plan and requested image, not a signed
attestation. A failed install due to missing cache is not retried online.

## Limitations and authority

No network access is requested for the container, but host isolation is independently
operator-controlled and never proven by this receipt. Docker daemon/socket, executable,
image, cache and tracked source are trusted inputs. Cache path is bound, contents are
not fingerprinted; changes or concurrent writes can affect reproducibility. Use a
stable dedicated cache. Container can read mounted public cache and source; Docker is
not a complete hostile-code security boundary. Tracked secrets are not filtered; use
only reviewed public source. Host subprocesses and Docker may have side effects such
as daemon logs and temporary files. Timeout does not prove daemon-side cleanup;
inspect local containers after interruption. No hard wall-clock bound for every Git
operation, no cross-platform ACL manager, no authenticated consent or durable journal.
No automatic acceptance, patch application to source, commits, PRs or merge. A green
build is not a security audit. Model proposal generation and actual dependency/cache
field qualification remain separate. CI mocks Docker; real offline Windows/Linux
acceptance and image/cache capacity are unverified.

Test: PYTHONPATH=server pytest -q server/tests/test_phi_forge_r05a.py
