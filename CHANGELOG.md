## [1.0.0-rc1] - 2026-03-01

### Changed
- Promoted product identity to `v1.0.0-rc1` across config, system API, Streamlit title/banner, README/docs, and web package metadata.
- Hardened run control endpoints with explicit not-found errors for pause/resume/clone-agent paths.
- Improved doctor output with actionable `next_steps` guidance for missing optional dependencies.
- Polished Windows launcher to start API + Streamlit for one-click local startup.
- Expanded release-readiness smoke checks for workflow replay and worker fallback behavior.

## [0.9.7] - 2026-03-01

### Changed
- Unified release/version branding in API, Streamlit, config, and docs for `v0.9.7`.
- Polished Streamlit dashboard labeling for first-run clarity, approvals, and inspector discoverability.
- Refreshed README and added focused docs for quickstart, operator mode, two-PC setup, troubleshooting, and release history.

# Changelog

All notable changes to this project are documented in this file.

## [0.9.6] - 2026-03-01
### Added
- Added one-click local launchers (`launch_agentora.bat`, `launch_agentora.ps1`) and a Python bootstrap helper (`scripts/agentora_bootstrap.py`).
- Added system diagnostics and bootstrap APIs (`/api/system/doctor`, `/api/system/bootstrap`, `/api/system/version`, `/api/system/health`).
- Added Operator Mode runtime entities and APIs for stepwise execution, pause/resume, and step controls.
- Added Docker and compose deployment profiles for single-PC and two-node local network setups.
- Added tests for operator mode, system doctor, and bootstrap.

### Changed
- Upgraded FastAPI app title/version metadata to `v0.9.6`.
- Expanded action approval logging and scope previews.
- Refreshed README for modern quickstart, operator center, and release progression.

## [0.9.0-rc1] - 2026-03-01
### Added
- Added first public release docs: `CHANGELOG.md`, `RELEASE_NOTES.md`, and `DEPLOYMENT.md`.
- Added optional release packaging script at `scripts/create_release_archive.sh`.
- Added optional tag-triggered GitHub release workflow (`.github/workflows/release.yml`).

### Changed
- Normalized public version metadata to `0.9.0-rc1` across README, Streamlit/FastAPI titles, and `web/package.json`.
- Clarified Streamlit-first runtime in README and `.env.example` with explicit embedded/HTTP mode guidance.
- Updated archive packaging naming from older hardcoded release labels to version-derived output.

### Notes
- This is the first public release candidate for GitHub publication.
- Local-first, offline-first, and Ollama-first defaults are preserved.
