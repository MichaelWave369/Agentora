# Agentora Φ Neural Research R1: proposal-only experiment conductor

**Status: local/offline operator review lane.** This is an original small integration with PhiStream and PhiRepoNerve. It borrows the *idea* of bounded experiments from Karpathy's `autoresearch`, not its training code or model weights. It does not import or vendor any Karpathy source.

## Ecosystem responsibility

| Component | Responsibility | Boundary |
|---|---|---|
| PhiStream | Run explicit tiny byte-level Transformer experiments | Training requires `--approve-training`; no automatic GPU execution |
| PhiRepoNerve | Hash evidence bytes and compare self-reported eligible runs | Source/data/metrics consistency is not authenticated hardware execution |
| Agentora R1 (this PR) | Anchor a baseline receipt; deterministically propose **one** hyperparameter change; review candidate metadata | No subprocess, network, credentials, schedules, PR writes, promotion or model selection |
| PhiDiscovery | Later: separate discipline-specific hypotheses and independently validated evidence | A better language-model score is *not* a scientific discovery |
| PhiMathAtelier / PhiOS | Later: visual, read-only experiment monitor | No release/merge rights |

## Prerequisites

1. Work with the merged `PhiStream` tiny pilot and merged `PhiRepoNerve` neural receipt adapter. You need Python 3.10+, compatible local PyTorch, and a locally approved small UTF-8 dataset.
2. Run a **deliberately approved** baseline on the operator machine, for example:

```powershell
# Inside your PhiStream checkout. Keep artifacts outside Git and do not publish them.
python -m phistream.neural_tiny preflight --data .\examples\demo-phi-bytes.txt --context 16
python -m phistream.neural_tiny train --data .\examples\demo-phi-bytes.txt --out-dir C:\phi-neural\baseline --approve-training --device cpu --context 16 --dim 32 --heads 2 --layers 1 --batch 4 --steps 12 --lr 0.003 --seconds 120 --vram-mb 10240 --seed 369 --study-id phi-study --run-id baseline
```

3. From your PhiRepoNerve checkout, record the original evidence. Use the **same source file** that the baseline actually executed, not a later-edited trainer.

```powershell
python -m phireponerve.neural_lab record --plan C:\phi-neural\baseline\plan.json --log C:\phi-neural\baseline\metrics.log --code C:\src\PhiStream\phistream\neural_tiny.py --out C:\phi-neural\baseline-receipt.json
python -m phireponerve.neural_lab verify --receipt C:\phi-neural\baseline-receipt.json --log C:\phi-neural\baseline\metrics.log --code C:\src\PhiStream\phistream\neural_tiny.py
```

4. From the Agentora checkout, inspect the baseline evidence and make a **review-only** proposal. Replace paths as needed:

```powershell
$base = @(
  '--meta', 'C:\phi-neural\baseline\run-meta.json',
  '--receipt', 'C:\phi-neural\baseline-receipt.json',
  '--data', 'C:\src\PhiStream\examples\demo-phi-bytes.txt',
  '--log', 'C:\phi-neural\baseline\metrics.log',
  '--code', 'C:\src\PhiStream\phistream\neural_tiny.py'
)
python .\scripts\neural_research_r1.py preflight @base
python .\scripts\neural_research_r1.py propose @base --parameter lr --value 0.0025 --out C:\phi-neural\candidate-proposal.json
python .\scripts\neural_research_r1.py verify @base --proposal C:\phi-neural\candidate-proposal.json
```

The proposal's `candidate` object contains **all** parameters needed for a **manually reconstructed** PhiStream training command. Set `--run-id` to the proposal's deterministic `trial-*` ID. Retain the same dataset, context, device/hardware, seed, steps, time cap and VRAM cap. Change only the one approved parameter. The proposer never builds or runs shell commands, and output files use exclusive-create semantics.

5. Record and re-verify the candidate separately in PhiRepoNerve, then call its `compare` command. Agentora's optional `assess` can flag a candidate *for independent review*, but cannot accept it:

```powershell
python .\scripts\neural_research_r1.py assess @base --proposal C:\phi-neural\candidate-proposal.json --candidate-receipt C:\phi-neural\candidate-receipt.json --min-delta 0.001
python -m phireponerve.neural_lab compare --before C:\phi-neural\baseline-receipt.json --after C:\phi-neural\candidate-receipt.json --min-delta 0.001
```

## Design protections

- Inputs: `run-meta.json`, RepoNerve `receipt.json`, exact dataset bytes, original trainer source, and original metrics log. All are local and capped at 4 MiB (dataset capped at 1 MiB); symlinks are rejected. The tool reads them but does not execute them.
- Baseline SHA-256: independently recomputed for dataset, code, metrics log and receipt. Checks the frozen evaluator and tokenizer digests **agree across the supplied files**, but cannot authenticate who produced them or what hardware executed them.
- Proposal digest binds to the baseline receipt hash and the **single** changed parameter/value. Proposal validation rebuilds the exact plan from the original baseline rather than trusting copied approval flags.
- Only `lr`, `dim`, `heads`, `layers`, or `batch` may change in R1. Context, tokenizer, evaluator, dataset, seed, fixed optimizer step count, machine identity, time budget and VRAM cap are frozen for comparison. Architectural changes may require independent parameter-count or performance qualification.
- Candidate assessment additionally requires a matching study, proposed run ID, source digest, evaluation contract and step count. **It still does not verify candidate log/code files; RepoNerve `verify` must be run separately.**
- Operator-supplied data and receipts are *self-attested*. Even if all hash checks pass, an actor capable of fabricating a consistent set of inputs can fool these checks. Held-out evaluation can leak through repeated adaptation; use fresh independent seeds, truly held-out data, preregistered thresholds, and negative controls before claiming generalization.
- No scheduler, model loading, subprocess, shell command interpolation, file overwrite, network calls, automatic repository writes, model promotion, or autonomous PR merge.

## Test

```powershell
python -m unittest discover -s tests -p 'test_neural_research_r1.py' -v
```

Local cross-repository smoke tested the actual PhiStream `neural_tiny.run()` and PhiRepoNerve `neural_lab.record()` on CPU, then Agentora's `inspect_baseline()`, `propose()` and `verify_proposal()`. This is a **pipeline compatibility test**, not a GPU validation or model-quality result.

## Next rung

After actual RTX 5070 operator-run receipts exist, add an **opt-in review queue** with independent evaluation and governance. Do not enable agents to change evaluator code or accept their own results. The first GPU performance claims must come from local evidence, not CI.