# Security

## Threat Model
- Agentora is local-first and defaults to `localhost_only` network mode.
- Outbound requests are blocked unless localhost or allowlisted.
- No telemetry and no automated external scraping.

## Data Storage
- SQLite only.
- Local artifacts/uploads under `server/data/` (gitignored).
- Optional encryption-at-rest can be enabled via `AGENTORA_ENCRYPTION_KEY`.

## LAN Mode
- Explicit opt-in required.
- Join codes and host approval gate are required.
