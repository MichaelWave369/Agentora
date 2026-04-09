# Agentora — Agent Instructions

## Mission

Agentora is a local-first multi-agent orchestration studio. Preserve stability, observability, lineage, and operator control.

## Priorities

* Keep orchestration behavior understandable and auditable.
* Preserve mission loop reliability.
* Prefer small, reversible changes.
* Maintain clean boundaries between orchestration, UI, persistence, and integrations.
* Protect local-first behavior and export/import workflows.

## Rules

* Do not work directly on `main`.
* Do not introduce unnecessary dependencies.
* Do not rewrite architecture unless explicitly asked.
* Do not remove lineage, audit, or observability features without approval.
* Do not push, merge, or delete branches unless explicitly instructed.
* Do not modify vendored or third-party code unless explicitly requested.

## Muse workflow

If Muse is available, prefer Muse commands over grep/cat/git for inspection:

* discover symbols first
* inspect exact symbols
* check impact before changing
* check contract/behavior before deleting or refactoring
* prefer semantic reasoning over text search

Suggested analysis flow:

1. `muse code symbols --json`
2. `muse code find-symbol --name <target> --json`
3. `muse code cat "<symbol_address>" --json`
4. `muse code impact "<symbol_address>" --json`
5. `muse code contract "<symbol_address>" --json`

## Safety

* Do not delete code automatically just because it appears unused.
* Treat dead-code results as candidates until impact and contract signals are checked.
* Explain reasoning before making structural changes.
* Prefer dry-run, read-only, or analysis-first workflows.

## Testing

* Run the smallest relevant tests first.
* If orchestration, state flow, lineage, or export/import code changes, call that out explicitly.
* Favor stability over cleverness.

## Current priority

Prepare this repository for Muse-native agent workflows while preserving Agentora’s local-first orchestration model.
