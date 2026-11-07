# Agentora ↔ PhiRepoNerve R1: read-only public observation bridge

**Status:** optional integration proposal. No agents are started, no source is changed, and no merge or deployment authority is created.

## Source contract

RepoNerve R1 serves local, read-only API routes at http://127.0.0.1:8765.
Agentora reads **only** /api/summary, /api/repos (fully paginated), and a
bounded recent /api/events window, with no GitHub write tokens.

The adapter fails closed if the latest scan failed, is too old (>36 hours),
changes during pagination, has inconsistent inventory counts, or contains
untrusted repository identities. GitHub numeric ID is the stable key. A
scanner's "complete" listing is complete only for its current permissions.
Push activity is not proof of CI success. Observations convey zero authority.

## Local usage

1. Start RepoNerve and run a successful scan.
2. Run Agentora with AGENTORA_REPONERVE_ENABLED=true to allow read-only
   GET /api/integrations/phireponerve/public-observations. This optional
   endpoint returns **public-only** metadata, never private projects.
3. Or export an explicitly reviewed file:

   python scripts/export_phireponerve_public.py --output ./fleet-public.json

4. Import that file into PhiMadaPrime's RepoNerve tab (after its matching PR).
   Review before sharing or publishing. Do not upload RepoNerve's SQLite DB.

RepoNerve's original unauthenticated R1 localhost API must **never** be
exposed on a public interface. Agentora's exposed bridge is public-only,
even if the backing scan includes private projects. Private fleet
management needs a separate, authenticated and authorized channel.

## Non-goals and next rung

This is a verified shape / privacy handshake, not live job dispatch.
Agentora's existing AgentCeption integration remains the executor path.
Next: add explicit local authenticated worker assignment, durable
repo-steward context, idempotent event intake, exact-SHA evidence,
leased task ownership, and policy-constrained merge handoffs.

No external endpoint, browser cross-origin localhost access, secret
export, automatic deployment, or live public Pages feed is introduced.
