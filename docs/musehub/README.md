# Agentora MuseHub Health Sprint R1

This directory holds an evidence-based review of MuseHub's dead-code flags
and the associated local-first audit workflow.

- [FINDINGS.md](FINDINGS.md): 28 candidate classifications and the evidence
  behind the protected, legacy-review, and contract-review decisions.
- [scripts/musehub_dead_audit.py](../../scripts/musehub_dead_audit.py):
  stdlib-only, read-only AST **reference hints**, never deletion authorization.
- [server/tests/test_musehub_dead_guard.py](../../server/tests/test_musehub_dead_guard.py):
  regression guards for callbacks, SQLModel tables, a development-board
  fixture, legacy memory behavior, and mock integration contracts.

## Run locally

From the Agentora repository root, with Python 3.12+:

    python scripts/musehub_dead_audit.py . --output musehub-r1-report.md --json-output musehub-r1-report.json

Keep generated reports outside version control unless intentionally reviewing
them; they contain checkout paths and may change as the repository evolves.
Run focused regression tests with the existing project dependencies installed:

On Windows PowerShell:

    $env:AGENTORA_USE_MOCK_OLLAMA="true"
    $env:AGENTORA_USE_MOCK_VOICE="true"
    $env:PYTHONPATH=".;server"
    py -m pytest -q server/tests/test_musehub_dead_guard.py

On Linux/macOS:

    AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=.:server python -m pytest -q server/tests/test_musehub_dead_guard.py

Then run the full backend suite:

    AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=.:server python -m pytest -q server/tests

The existing ci workflow runs the full server test suite on PRs, so no new
workflow privileges, services, or tokens are needed.

## Scope and safety

- This sprint does not delete any flagged functions, database tables, APIs,
  fixtures, or related stored data.
- The three Python HTMLParser callbacks are framework-dispatched and must be
  preserved.
- The R1H normalize_label fixture is an intentionally byte-pinned example.
- Artifact and VoiceSetting are SQLModel table declarations: schema removal
  requires a separate migration and compatibility review.
- The two legacy memory helpers are **candidates for later review**, not yet
  authorized to remove. Existing behavior is regression-tested.
- MuseHub's 81/100 is an analysis heuristic, not a test pass percentage.
  Reanalysis on an imported revision is required to measure any score delta.
- Before any deletion or restructuring, follow AGENTS.md's Muse symbol, impact,
  contract, and smallest-relevant-test workflow. Human approval remains required.

Initial evidence is pinned to GitHub main SHA
63e1c4eae7c395d32ea8e35ed1279368a7886a72, with MuseHub's public
report retrieved on 2026-11-21. The MuseHub UI did not expose the original
Git commit SHA, so matching commit titles do not prove identical trees.
