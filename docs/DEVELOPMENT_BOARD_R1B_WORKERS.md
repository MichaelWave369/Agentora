# Φ Development Board R1-B · Controlled builder/verifier subprocess pilot

**Scope: R1-B is the first actual local execution of two distinct fixed-function
worker processes, not autonomous AI coding.** Its only build target is a new
`index.html` in a freshly created scratch directory. The builder runs in one
Python child process; the verifier launches in a second Python child process,
reopens the artifact, checks exact content/spec hashes and semantic HTML rules,
and returns an independent *local self-report*. This is a rehearsal for later
Agentora → PhiBot → GitPorch execution, **not** an OS sandbox, authenticated
multi-agent service, signed attestation or software correctness proof.

## What is runnable now

From a local checkout of Agentora on Windows 11, Python 3.12+:

```powershell
cd <local-Agentora-clone>
$env:PYTHONPATH = "server"
python -m app.services.development_board.r1b_cli plan examples/development-board/r1b-fixture-spec.json
```

The plan command reads the supplied **declarative JSON** and prints a canonical
64-character `frozen_spec_digest`. Review the entire spec before running.
Then replace the placeholder below with that **exact digest you just observed**:

```powershell
python -m app.services.development_board.r1b_cli run examples/development-board/r1b-fixture-spec.json --approve-spec-digest <64-hex-digest> --i-approve-local-fixture
```

The run command creates one new `agentora-devboard-r1b-...` workspace in the
system temporary folder, with:

- `frozen-spec.json` — canonical copy of the reviewed spec
- `artifact/index.html` — bounded original static HTML output, not executed
- `review-receipt.json` — only after both workers and the parent SHA recheck pass

Inspect the file locally in a browser. Delete the temporary workspace yourself
when finished. Do not put secrets or private task data into a spec; the frozen
copy remains until the workspace is deleted.

The plan command never builds anything. The run command refuses an absent,
malformed or mismatching digest and explicit approval switch **before creating
a scratch directory**. The switch is an operator acknowledgement, not secure
authentication. A later edit to the spec changes its digest and refuses the
old acknowledgement.

## Constraints and honest limits

- Exactly four text fields plus schema are allowed. No arbitrary target file,
  shell command, executable script, dependency, network address or agent tools
  can be specified by the input.
- The builder is a **deterministic, fixed-template local worker**, not PhiBot
  or an LLM generating novel code. It never writes to an existing output.
- A different Python child process implements the verifier. The verifier
  never executes generated code. It validates size, expected SHA-256, frozen
  spec digest, exact headline/title/description/action text, navigation and
  viewport, and rejects external resources/scripts.
- The parent hashes the artifact before **and after** verifier execution to
  detect a changed file. Distinct OS processes are not strong actor isolation:
  both run under the same local user account and share filesystem privileges.
- Child workers inherit a deliberately reduced process environment, have
  bounded output and a ten-second timeout. These limits do **not** turn the
  setup into a hardened container or secure sandbox.
- No service listener, background schedule, Git operations, GitHub token,
  Ollama API call, PhiBot dispatch, CI attestation, merge, or deployment is
  performed.
- `REVIEW_READY_NOT_AUTHORIZED` means only the bounded static fixture
  checks passed **as locally self-reported**. In every case
  `eligible_for_merge=false`.

## CI verification

```bash
AGENTORA_USE_MOCK_OLLAMA=true AGENTORA_USE_MOCK_VOICE=true PYTHONPATH=server pytest -q server/tests/test_development_board_r1b.py
```

Normal GitHub Actions also runs the full backend suite on Python 3.12/3.13
and builds the frontend. The tests launch both real child processes, test
escape of hostile HTML strings, simulate artifact mutation after verification,
reject changed/duplicate spec keys, disallow scope-exploding inputs and
confirm no HTTP endpoint dispatches workers. CI is not a substitute for
running the fixture on the actual local Windows machine.

## Next field gates before model-driven code

1. Run the sample on your Windows PC; capture a **redacted** field receipt,
   confirm both distinct worker roles and generated HTML on disk.
2. Complete an observed Code Brown first-use usability test on the local
   Agentora Development Board. CI never certifies human usability.
3. Build a separately allowed, opt-in PhiBot/Ollama worker adapter that
   proposes only an explicitly authorized narrow file change, writes only
   a draft candidate, and cannot choose its own verifier.
4. Run verification in a **proper sandbox** with a distinct identity and
   independently acquired commit/check evidence, not merely two Python
   processes on the same account.
5. Require renewed approval after every spec, branch, commit or evidence
   change. Human merge/release decision stays separate.

This is an original implementation of the **3 specifies → 6 builds → 9
proves → human decides** philosophy, applied to the smallest real execution
we can measure without taking away user control.
