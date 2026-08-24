# Technical reference

Read this only after the product overview. The dashboard deliberately uses
plain business language; this page maps that language to the implementation.

## Architecture

| Product term | Implementation |
|---|---|
| Finance Controller workflow | LangGraph state machine in `agent/workflow.py` |
| Reconciliation engine | LedgerGraph in `agent/ledger_graph.py` |
| Possible grouped matches | bounded dynamic-programming subset-sum generation |
| Whole-batch answer | OR-Tools CP-SAT weighted set-packing model |
| Extra risk checks | deterministic GraphShield signals in `agent/graph_intelligence.py` |
| Explanation assistant | local Qwen 3.5 4B GGUF through llama.cpp |
| Web product | Next.js dashboard in `web/` and FastAPI in `dashboard/` |

## Reconciliation guarantees

- `Decimal` money arithmetic and signed-money conservation
- direct, 1:N, N:1, and bounded N:M hypotheses
- each bank and settlement node used at most once
- exact global optimization over the generated candidate set
- ties, solver timeouts, non-optimal statuses, and incomplete candidate coverage
  fail closed for affected records
- candidate proofs include accepted evidence and rejected alternatives

Group size remains bounded by configuration. Dynamic programming reduces the
cost of generating equal-total subsets; CP-SAT selects the best compatible
groups. Larger bounds increase the search space and may hit time or candidate
caps, which are reported as review states rather than silently accepted results.

## AI boundary

Qwen is accessed through `agent/model_gateway.py`. It receives only retrieved,
read-only evidence. Reconciliation, risk decisions, amounts, journal construction,
approval, and posting do not depend on model output. The API probes the observed
model health, and the UI clearly reports GPU availability or deterministic fallback.

## Evaluation layers

1. **Known-rule tests:** generated fixtures share the declared anomaly families.
   These are implementation and regression checks.
2. **Multi-seed tests:** the same rules run across varied generated batches.
3. **Known-miss replay:** controls added after analysing earlier misses are scored
   only as regression evidence.
4. **Frozen-detector test:** the detector source is hashed before new temporal,
   aggregate, and control-plane fraud mutations run. Its misses remain disclosed.

This separation prevents a control-replay result from being presented as unseen
fraud validation.

## Key commands

```powershell
python run.py
python -m eval.suite
python -m unittest discover -v
python -m agent.qa "Why was BNK000015 held for review?"
```

See [Local setup](LOCAL_SETUP.md) for service commands and
[Data policy](DATA_POLICY.md) for source boundaries.
