# ΦDiscovery Blind Reviewer Bridge (Agentora R0.3)

**Status: opt-in research adapter, no confirmed live machine run.** This endpoint is NOT Agentora's normal `/api/runs` multi-agent workflow. It is a narrow text-only local model review transport designed to preserve blind first-pass critiques.

## Endpoint

`POST http://127.0.0.1:8088/api/discovery/review`

Request includes an untouched `phidiscovery.reviewer-packets.v0.2` packet and an explicitly allowlisted installed Ollama model ID. A required `x-discovery-review-key` header authenticates the local operator. The server recalculates the packet SHA-256 and binds candidate and role. It uses Agentora's existing `OllamaClient.chat_structured` with a fixed tool-free system prompt, and returns a `agentora.discovery-review.v0.3` receipt containing the model's **unverified** answer. The endpoint does not access Agentora agents, tools, memory, team runs, SQLite, or worker queues. No peer answers are supplied.

## Operator configuration (private .env, not checked in)

```dotenv
AGENTORA_DISCOVERY_REVIEW_ENABLED=true
AGENTORA_DISCOVERY_REVIEW_KEY=<generate-a-unique-private-secret-of-at-least-24-characters>
AGENTORA_DISCOVERY_REVIEW_MODELS=qwen3:4b,gemma3:12b
AGENTORA_USE_MOCK_OLLAMA=false
OLLAMA_URL=http://127.0.0.1:11434
```

Use Agentora's ordinary loopback-only FastAPI server, for example:

```powershell
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```

Keep the operator key **private**. The key is sent on localhost and is never committed. A local browser Origin header is deliberately rejected; remote network clients are rejected using the TCP client address. The configured `OLLAMA_URL` must be loopback HTTP. Models must be present in the explicit allowlist; missing or unavailable models cause refusal, never download/fallback.

If `AGENTORA_USE_MOCK_OLLAMA=true` the adapter rejects inference, rather than mistaking mock text for a scientific review. Default is disabled. This HTTP endpoint is not a general OpenAI-compatible API.

## ΦDiscovery integration

The companion PhiDiscovery CLI's `review-agentora` command generates role-bound packets, calls this endpoint sequentially (one isolated request per role), validates each returned receipt again, and stores a private JSON bundle. Each call is a real model invocation **only when both CLI approval flags and server opt-in are configured**.

Reviewers may share training data or weights, even if different model names are selected. **Role isolation is not evidence independence** and no agent output is counted as a laboratory observation. Reconcile with PhiDiscovery's `review-compare` command and human assessment.

## Limitations

- Responses are not authenticated checkpoint attestations. A malicious or compromised local service is not prevented by content hashes.
- There is no scientific source retrieval, physical experiment, automatic publishing, broad Agentora team orchestration, or background execution.
- The endpoint returns structured proposals, not validated science.
- Local secrets and outputs should not be placed in shared/public Git repositories.
- Additional security work (mutual authentication, auth rate limiting, TLS for any non-local deployment) would be required before exposing beyond loopback. **Do not expose this route to a network.**
