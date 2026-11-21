# Agentora R1: MuseHub Code Health Triage

**Reviewed:** 2026-11-21 (Pacific)  
**GitHub:** `MichaelWave369/Agentora` at `63e1c4eae7c395d32ea8e35ed1279368a7886a72` (main, 2026-11-19)  
**MuseHub:** https://musehub.ai/gabriel/agentora/intel/dead (28 reported candidates; 3 high, 25 medium)  
**Prior visible health score:** 81/100, Good (score breakdown could not be retrieved from public HTML).  
**MuseHub import evidence:** latest commit title matches GitHub main's Fleet R9 / PR #165; the MuseHub UI does not display the original Git SHA as proof of identical snapshots.

## Evidence-backed findings

1. **Three definite indirect callbacks:** `Witness.handle_starttag`, `Witness.handle_data`, and `Witness.handle_endtag` override `HTMLParser` callbacks. The parser dispatches them dynamically; preserve them.
2. **One intentionally retained exact fixture:** `r1h_packet.py` hardcodes `TARGET=examples/development-board/r1h-demo-label.py` and the same `normalize_label` function body in its `BEFORE` fixture. Removing or casually editing the file would break R1H's exact-source challenge.
3. **Two ORM declarations:** `Artifact` and `VoiceSetting` have `table=True`; `app.db.create_db_and_tables()` imports models and registers SQLModel metadata. Direct caller counts do not decide whether a table is required. Preserve without schema/migration review.
4. **Two legacy memory helpers need the first real cleanup investigation:** `remember` and `recall` in `services/memory.py` are standalone functions. Current memory router uses runtime capsule/maintenance modules instead. That suggests possible legacy status but does not prove absence of external callers.
5. **Two integration client methods have behavior:** `AgentCeptionClient.list_job_artifacts()` and `PhiOSClient.write_memory()` have implemented mock and HTTP paths. Test the public bridge contract before retiring either.
6. **Historical hotspots are not defects:** `server/app/main.py` has 41 MuseHub changes but is only 79 lines in current main. Moving code solely to reset churn would game the metric.
7. **Latest main CI passed:** GitHub Actions `ci` run 44636970912 (push event, 2026-11-19) succeeded. This is a baseline run, not a test of the files in this bundle.

## Candidate classification (all 28)

| # | MuseHub symbol | MuseHub confidence | R1 classification |
|---:|---|---|---|
| 1 | `examples/development-board/r1h-demo-label.py::normalize_label` | high | protected-fixture |
| 2 | `server/app/services/memory.py::recall` | high | legacy-review |
| 3 | `server/app/services/memory.py::remember` | high | legacy-review |
| 4 | `server/app/integrations/agentception_client.py::AgentCeptionClient.list_job_artifacts` | medium | integration-contract |
| 5 | `server/app/integrations/phios_client.py::PhiOSClient.write_memory` | medium | integration-contract |
| 6 | `server/app/integrations/schemas.py::AlertEventRecord` | medium | schema-contract |
| 7 | `server/app/integrations/schemas.py::LineageTreeResponse` | medium | schema-contract |
| 8 | `server/app/integrations/schemas.py::MissionPatternMemoryRecord` | medium | schema-contract |
| 9 | `server/app/integrations/schemas.py::OperatorDecisionEventRecord` | medium | schema-contract |
| 10 | `server/app/integrations/schemas.py::WatcherEventRecord` | medium | schema-contract |
| 11 | `server/app/models.py::Artifact` | medium | protected-orm |
| 12 | `server/app/models.py::VoiceSetting` | medium | protected-orm |
| 13 | `server/app/schemas.py::CapsuleLayerUpdateIn` | medium | schema-contract |
| 14 | `server/app/schemas.py::MemoryFeedbackIn` | medium | schema-contract |
| 15 | `server/app/schemas.py::MemoryMaintenanceIn` | medium | schema-contract |
| 16 | `server/app/services/development_board/r1b_verifier_worker.py::Witness.handle_data` | medium | protected-callback |
| 17 | `server/app/services/development_board/r1b_verifier_worker.py::Witness.handle_endtag` | medium | protected-callback |
| 18 | `server/app/services/development_board/r1b_verifier_worker.py::Witness.handle_starttag` | medium | protected-callback |
| 19 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator.get_cached_persona_matrix` | medium | orchestration-contract |
| 20 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator.get_cached_persona_trends` | medium | orchestration-contract |
| 21 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator.get_cross_root_persona_summary` | medium | orchestration-contract |
| 22 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator.maybe_attach_pattern_recommendations` | medium | orchestration-contract |
| 23 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator.run_software_task_with_context` | medium | orchestration-contract |
| 24 | `server/app/services/integration_orchestrator.py::IntegrationOrchestrator._upsert_pattern_from_candidate` | medium | orchestration-contract |
| 25 | `server/app/services/multimodal/service.py::model_can_vision` | medium | capability-review |
| 26 | `server/app/services/ollama_client.py::OllamaClient.chat_with_tools` | medium | model-contract |
| 27 | `server/app/services/ollama_client.py::OllamaClient.stream_chat` | medium | model-contract |
| 28 | `server/app/services/runtime/schemas.py::CapsuleSearchResult` | medium | schema-contract |

## Decision rules

- **Protect now (6):** the three HTMLParser callbacks, two SQLModel tables, and the exact R1H fixture. Add/maintain tests. MuseHub's 'dead' label is not an instruction to delete.
- **Contract review (20):** methods, DTO classes, and capability helpers. First inspect inbound clients, import/exports, dynamic lookup, HTTP schemas, and test coverage; preserve backwards-compatible contracts.
- **Legacy cleanup candidates (2):** `services/memory.py::remember` and `::recall`. Confirm no importers in production/tests, no documented public API, no downstream consumers, and safe migration; then consider a separate small reviewed PR. Do not alter SQLite tables or stored rows.

## Verification gates for a future PR

1. Identify MuseHub's four score penalties (dead, hotspot, coupling, breakage) through its read-only MCP `musehub_intel_health_score`; the public page does not expose the breakdown.
2. Run `musehub_dead_audit.py` locally; inspect reference hints manually and conduct exact symbol/impact/contract review in Muse, as required by `AGENTS.md`.
3. Run the prepared regression tests with mock integrations and no external services. Then run `py -m pytest -q server/tests` and any relevant Windows tests.
4. Preserve database schema, disabled-by-default integration behavior, and existing operator gates. Avoid churn-score tricks.
5. Review the draft PR with exact-head CI; do not merge or delete code as a scoring shortcut. Compare MuseHub's reindexed score after the new commit is imported.

## Scope and limitations

This triage began with read-only MuseHub/GitHub evidence and the baseline CI. The R1 pull request adds an auditable scanner and regression tests, but its exact-head CI and downstream MuseHub score require separate verification. No production code or data is deleted.

Sources: https://musehub.ai/gabriel/agentora/intel/dead ; https://musehub.ai/gabriel/agentora/intel/hotspots ; https://github.com/MichaelWave369/Agentora/tree/63e1c4eae7c395d32ea8e35ed1279368a7886a72 ; https://github.com/MichaelWave369/Agentora/actions/runs/44636970912