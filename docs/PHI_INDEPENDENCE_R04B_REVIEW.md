# Phi Independence R04-B — consent-bound tool-free local review

Experimental, no live workstation validation. R04-A remains unchanged.
The new review endpoint is separately disabled by default. It consumes the exact
R04-A selected answer packet plus model tag and purpose. No new repository.

## Private pilot

Use the UTF-8 JSONL export and private directory procedure in
[ R04-A](PHI_INDEPENDENCE_R04_BRIDGE.md). In Agentora, with PYTHONPATH=server:

```powershell
python -m app.services.phibuddy_review_cli D:/PhiVault/buddy-events.jsonl --sequence 2 --model qwen3:4b
```

The preview prints private selected content and a consent_sha256. Review both;
sequence and model are examples. Configure the same private 64-hex bridge key
as R04-A in client/server environments. Set AGENTORA_PHIBUDDY_BRIDGE_ENABLED=1,
AGENTORA_PHIBUDDY_REVIEW_ENABLED=1, AGENTORA_PHIBUDDY_REVIEW_MODELS to explicitly
approved exact local model tags, AGENTORA_USE_MOCK_OLLAMA=false and
OLLAMA_URL=http://127.0.0.1:11434 in the server environment. Preinstall models;
do not use cloud-backed aliases. Independently block external network while
retaining loopback. Start Agentora as in R04-A with --no-proxy-headers.

```powershell
python -m app.services.phibuddy_review_cli D:/PhiVault/buddy-events.jsonl --sequence 2 --model qwen3:4b --approve-digest YOUR_PREVIEW_DIGEST --confirm-offline
```

Changed source bytes, selected event, model or purpose invalidate the prior digest.
Digest is not secret and not a signature or proof of human consent: a caller
with the key can create its own requests. The server checks packet consistency,
not original source/completion. No replay prevention or durable one-use token;
each invocation may incur a new local model call. No retries in bridge client.

## Runtime boundaries

Fixed loopback endpoints; no environment proxies or redirects in provider client.
Separate opt-in, exact Host, no browser Origin, key, real provider config, allowlist.
One bounded structured chat request, no tools, no memory, no worker or run creation.
Provider output must be completed, match requested model string, contain no tool
calls and satisfy exact review schema. Model name is self-reported, not attested.
Prompt contains selected proposal only; it is untrusted, not authority. Review
output is untrusted too. Prompt injection can still influence review content.
Result carries review digest and false authority/verification fields; no execution
or independent source verification. Client validates exact receipt structure.

The bridge does not persist results, but stdout, daemon logs or other processes may.
Use private encrypted storage and avoid logs. A compromised local daemon could
forward traffic; operator offline confirmation is not measured. No protection
against malicious same-user processes. Provider request has 120s async deadline;
client socket timeout is per operation. No durable recovery, concurrency quota,
or hard end-to-end deadline. This is not a general-purpose service.

Tests: PYTHONPATH=server pytest -q server/tests/test_phibuddy_review.py.
Synthetic ASGI/HTTP tests, no real provider, no Windows acceptance. Next: isolated
workspace proposal/approval workflow, with explicit user permission for every effect.
