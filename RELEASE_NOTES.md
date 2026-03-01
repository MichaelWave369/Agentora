# Agentora 0.9.0-rc1 Release Notes

## Release summary
Agentora `0.9.0-rc1` is the first public GitHub release candidate focused on release hardening, version consistency, Streamlit-first runtime clarity, and deployment readiness.

## Highlights
- Streamlit remains the primary runtime/UI.
- FastAPI remains the orchestration/data backend.
- Runtime behavior is now clearly documented for:
  - `auto` mode (HTTP-first with embedded fallback)
  - explicit `http` mode
  - explicit `embedded` mode
- Public release docs and packaging flow are now included.

## Included in this RC
- Version normalization to `0.9.0-rc1`.
- Deployment and environment variable documentation.
- Optional release archive packaging script.
- Optional tag-based GitHub release workflow.
- No architectural rewrite; major features preserved.

## Recommended validation before tagging
1. `python -m pip install -r requirements.txt`
2. `AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=server pytest -q server/tests`
3. `python -c "import streamlit_app"`
4. `cd web && npm ci && npm run build`
5. `scripts/create_release_archive.sh 0.9.0-rc1`

## Known limitations
- Embedded mode uses FastAPI `TestClient` and is intended for local/dev convenience.
- Real model runtime requires local Ollama and model availability.
- React web scaffold remains optional and secondary to Streamlit-first runtime.
