# PhiConstruct R4: manual bounded training execution

R4 adds an explicitly triggered GitHub Actions Code Lab, not a new agent
orchestration or deployment service.

The operator supplies a task choice, an exact 40-character Agentora candidate
commit SHA, an existing PhiRepoNerve handoff SHA-256 (correlation claim only),
an approved immutable python:3.12-alpine@sha256:<64 hex> image reference,
and RUN_BOUNDED_CONSTRUCT_TRAINING.

A candidate's Python function is committed at one fixed path:
construct_candidates/retry-backoff-code.py or
construct_candidates/repo-slug-code.py.

The workflow runs only on main via workflow_dispatch. It checks out trusted
Agentora controller code at the triggering SHA, separately checks out the exact
candidate SHA, validates manifests copied from PhiRepoNerve, then runs seven
small deterministic checks in restricted network-disabled Docker containers.

The trusted host controller never imports the candidate Python directly.
Only a copy of one allowlisted file is read and mounted into a non-root,
read-only, capability-stripped container; no GitHub token, SSH key, root
workspace or Docker socket is passed to the container. The host compares
reported values and stores preflight.json and result.json in a review-only
GitHub Actions artifact named construct-r4-<run_id>.

Every report keeps independent pack approval, agent identity, lease
attestation, GitHub artifact validation, merge, dispatch, deployment, and
general competence claims FALSE. Passing verifies only the diagnostic cases
reported by the runner, not the author or generalized coding skills.

Important limits: Docker shares a kernel with its host and is not a proven
adversarial sandbox; a malicious submission may interfere with stdout or
hardcode the public task cases. The workflow is not automatically bound to
Agentora's local R3 worker lease. The immutable candidate SHA need not equal
the current main branch SHA. A SHA-256 handoff digest is not a signature.

CI tests stub the Docker runner; they do not execute untrusted code. The
manual workflow has not yet been run or independently audited here.
A future R5 must independently verify GitHub workflow identity and
SHA256-correlated artifacts and bind trustworthy evidence to an exact
approved training assignment without granting new permissions.
