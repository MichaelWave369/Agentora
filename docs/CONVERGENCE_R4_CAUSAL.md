# Convergence R4 · pinned causal DAG comparison

This Agentora-side research harness consumes the real Altermath R1 module at commit
[acac3a4e](https://github.com/MichaelWave369/Altermath/blob/acac3a4ea792f2b979b11f8dcccc1b298596ea0e/src/causal-belt.mjs).
It checks the exact Git blob before importing the verified bytes. CI checks out both public sources with no persisted credentials. The harness itself is offline, fixed-fixture, and dependency-free.

From Agentora, with a separately trusted checkout of that Altermath revision:
```sh
ALTERMATH_CHECKOUT=../Altermath node --test scripts/causal_convergence_r4.test.mjs
node scripts/causal_convergence_r4.mjs ../Altermath
```

The independent ordinary DAG evaluator uses ready-frontier scans and fixture functions rather than Altermath's compiler, permissions or receipt code. It compares outputs and frontiers under five predefined numeric cases. The Altermath-specific controls separately check revoked grants, insufficient fuel, cycles, cross-pocket data access and receipt tampering. A modified source is refused. Tests assert results and fuel accounting, deterministic reorder behavior and reproducible receipts.

Ten events have six unit dependency stages and maximum frontier width two. That is an illustrative work/depth relationship, not measured latency or speedup. Both paths are sequential. Fuel is abstract; there is no real resource measurement or general equivalence proof. No agent run, database, model, private data, worker, tool, deployment, runtime authority or changes to Agentora's orchestration engine. No routing promotion.

Next gate: expand frozen graphs and compare independently implemented policy semantics, then measure sequential versus structured concurrent execution on an explicitly authorized fixture worker. Keep real Agentora mission execution separate until its own authority and recovery review.
