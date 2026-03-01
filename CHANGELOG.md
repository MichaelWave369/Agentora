# Changelog

All notable changes to this project are documented in this file.

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
