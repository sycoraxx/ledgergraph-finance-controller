# Technical reference

Read this only after the product overview. The dashboard deliberately uses
plain business language; this page maps that language to the implementation.

## Architecture

| Product term | Implementation |
|---|---|
| Finance Controller workflow | LangGraph state machine in `agent/workflow.py` |
| Reconciliation engine | LedgerGraph in `agent/ledger_graph.py` |
| Declared large groups | cross-source group-key verification, up to 1,000 members per side |
| Small possible groups | bounded dynamic-programming subset-sum generation |
| Large inferred 1:N/N:1 groups | time-bounded CP-SAT membership search with a uniqueness proof |
| Whole-batch answer | OR-Tools CP-SAT weighted set-packing model |
| Extra risk checks | deterministic GraphShield signals in `agent/graph_intelligence.py` |
| Explanation assistant | optional OpenAI-compatible local or hosted model |
| Web product | Next.js dashboard in `web/` and FastAPI in `dashboard/` |

## Reconciliation guarantees

- `Decimal` money arithmetic and signed-money conservation
- direct, 1:N, N:1, and N:M hypotheses
- declared cross-source groups up to 1,000 members per side without subset enumeration
- inferred anchor groups up to 100 members from a 1,000-record evidence pool
- each bank and settlement node used at most once
- exact global optimization over the generated candidate set
- ties, solver timeouts, non-optimal statuses, and incomplete candidate coverage
  fail closed for affected records
- candidate proofs include accepted evidence and rejected alternatives

There are three candidate-generation paths. Dedicated
`reconciliation_group_id`, `payout_id`, or `batch_id` values that agree across
both sources define an atomic group whose totals and chronology are verified in
linear time. Small unknown groups use dynamic-programming subset-sum discovery.
Larger unknown 1:N and N:1 groups use a direct CP-SAT exact-sum membership model
and a second solve that rules out an equally supported alternative.

The whole-batch CP-SAT set-packing model still enforces one-use constraints
across the resulting candidates. A missing group counterpart, excess declared
membership, ambiguous membership, incomplete DP search, non-optimal solve, or
timeout marks the affected records unsafe and sends them to review. Arbitrary
unstructured N:M search is intentionally not advertised as tractable at 1,000
records per side.

## AI boundary

The optional model is accessed through `agent/model_gateway.py`. Question routing
is deterministic; the model receives only retrieved, read-only evidence after
the allowlisted lookup. Reconciliation, risk decisions, amounts, journal
construction, approval, and posting do not depend on model output. Local Qwen,
Groq, Gemini, and generic OpenAI-compatible endpoints are supported. The UI
reports AI explanations or built-in deterministic mode without exposing secrets.

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

```bash
python run.py
python -m eval.suite
python -m unittest discover -v
python -m agent.qa "Why was BNK000015 held for review?"
```

See the [README](README.md) for setup and service commands,
[Business operations](BUSINESS_OPERATIONS.md) for the operator runbook, and
[Data policy](DATA_POLICY.md) for source boundaries.
