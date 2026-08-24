# Finance Controller — Judge Guide

## The one-sentence pitch

A local, evidence-first finance controller reconciles Razorpay settlements
against simulated bank and ERP records, stops unexplained money, proposes
balanced journals behind a human gate, and uses a small local model only to
explain deterministic results.

## The problem

Finding a likely settlement match is not enough. A bank credit may match a
Razorpay settlement while one payment, refund, fee, tax, dispute, or adjustment
inside it remains unsupported. Finance teams need both a match and proof that
every component closes.

## What enters the controller

1. **Razorpay Test Mode/API-shaped exports** — simulated payments, refunds, and
   settlement components using official schemas.
2. **Simulated bank emulator** — credits, debits, UTR-like references,
   narrations, value dates, and running balances.
3. **Simulated merchant ERP** — independently generated cashbook approvals for
   operating credits and debits.

No real financial data or real money is used. See `DATA_POLICY.md`.

## What is deterministic

- All amount arithmetic uses `Decimal`.
- Settlement aggregation and bank matching.
- Global one-use optimization and exact signed-money conservation.
- Bounded 1:1, 1:N, N:1, and irreducible N:M reconciliation with proof certificates.
- Payment/refund/fee/tax/component verification.
- Credit and debit risk controls.
- Confidence thresholds and stopping rules.
- Balanced journal construction and idempotent proposal identifiers.
- Metrics, citations, timestamps, and the approval boundary.

## What Qwen does

Qwen receives a retrieved evidence object and turns it into readable text. It
cannot calculate a financial value, select a settlement match, change a control
threshold, approve a proposal, or post money.

## The evaluation layers

| Layer | Current result | Meaning |
|---|---:|---|
| Frozen-fixture conformance | 100% risk recall | Declared controls are implemented correctly on 87 entries. |
| Five-seed conformance | 100% across 435 entries | The same declared controls remain stable under generated variation. |
| OOD exact-control baseline | 84.4% recall, 100% precision | Preserved before/after baseline with ten relational misses. |
| Known-miss replay with GraphShield | 100% recall, 100% precision | Regression proof only: ten known relational misses are now controlled. |
| Post-freeze fraud holdout | 0.0% recall, 100% specificity | The unchanged detector misses all 35 new temporal, aggregate, master-data, and out-of-hours cases. |

Exact controls detect 54 of 64 dubious entries and report ten misses:

- five counterparty substitutions;
- five collusive duplicates backed by apparently valid approvals.

GraphShield uses the already supplied bank narration, ERP counterparty and
approver fields as graph nodes. It recovers all ten on the declared replay by
detecting broken counterparty edges and the combination of a rare approver with
a repeated economic motif. Because these features were introduced after miss
analysis, 100% is a control-replay result—not a claim about unseen production
fraud.

The post-freeze holdout is the actual generalization check. Its mutation
families were added after the detector was frozen, the detector source hash is
enforced, and GraphShield is not modified in response. The disclosed 0/35 result
is why this project claims narrow relational controls—not general fraud
detection.

## Are the discrepancies realistic?

The dashboard answers this per scenario instead of making one blanket claim.
Each risk or evaluation card shows a realism badge, its required evidence
sources, and a claim boundary:

- **Razorpay-native mechanic** — documented lifecycle behavior such as
  working-day settlement timing or net settlement components.
- **Cross-system integration failure** — plausible bank/ERP/export/ETL failure;
  not represented as a Razorpay defect.
- **Adversarial stress case** — difficult 1:N, N:1 or N:M reconciliation
  topology included for solver coverage, not production frequency.
- **ERP control / fraud anomaly** — plausible merchant-control behavior that
  requires approvals, vendor-master, invoice or cashbook evidence beyond a
  standard settlement feed.

The 13 / 12 / 12 / 13 topology balance is intentionally artificial. It proves
all four graph shapes execute at batch scale; it does not claim that real
merchant data has an even topology distribution.

## Why LedgerGraph is different

The controller does not greedily accept the first plausible row match. It
creates candidate edges between bank entries and Razorpay settlements, then
selects the best consistent explanation of the entire batch. Exact money and
one-use constraints are hard rules; fuzzy UTR/date evidence only ranks valid
hypotheses. It supports one-to-one, one-to-many, many-to-one, and irreducible
many-to-many flows. A grouped match is one atomic hyperedge, not a collection
of independently accepted pairwise links. A tie is
shown as an abstention. Clicking any selected edge reveals its proof
certificate and rejected alternatives.

The adversarial suite is intentionally separate from the 87-entry fixture. A
four-case calibration partition freezes threshold 65; LedgerGraph then resolves
7/7 held-out cases with zero false selections. Across all eleven cases it scores
11/11, compared with 6/11 and one false selection for the previous row-wise
L0/L1 matcher. This is synthetic reconciliation evidence—not a production fraud
claim.

## Three-minute demo script

### 0:00–0:30 — Judge Overview

State the problem and point to the three-source system map. Emphasise that
deterministic code owns money while Qwen only explains evidence.

### 0:30–1:05 — Run Current Batch

Click **Run current batch**. Show the 87 bank entries, nine dubious holds, 47
balanced proposals, zero automatic postings, and the extraction timestamp.
Explain that multi-seed and mutation suites are frozen offline artifacts, not
regenerated inside the interactive workflow.

### 1:05–1:35 — LedgerGraph

Open **LedgerGraph**. Show the full-batch node/edge counts, one proof
certificate, exact ₹0 residual, and the balanced solution mix: 13 direct, 12
aggregated, 12 split, and 13 irreducible many-to-many groups. Click a settlement
node to show its capture date, T+1/T+2 cycle, working-day path, and settled date.
Use the Thursday T+2 → Monday card to make weekend handling immediately legible.
Switch to **Before** and point out that 473 hypotheses reduce to 50 selections.
Each topology filter now separates hard-gate rejections from exact-money paths
rejected by the global one-use objective; click one of each to show the residual
or global-conflict blocker in plain language.

### 1:35–2:00 — Risk Review

Open one credit and one debit finding. Show observed text, expected evidence,
transaction time, extraction time, recommended action, and exact CSV citations.

### 2:00–2:25 — Evaluation Proof

Show the known-miss replay first: 84.4% → 100% is a regression control, not
validation. Then show the hash-locked post-freeze holdout: 0/35 fresh fraud rows
detected, 35 honest misses, and 100% specificity on 15 clean controls. This is
the strongest evidence that the evaluation is not tuned to tell a winning story.

### 2:25–2:45 — Settlement Q&A

Ask why a bank transaction was held. Explain that a deterministic read-only
tool retrieves the evidence before Qwen writes the answer.

### 2:45–3:00 — Human Gate

Open a balanced journal proposal. Show that its amounts are immutable and that
LangGraph pauses until a human approves or rejects it. Posting remains limited
to the local idempotent sandbox ledger.

## Vocabulary

- **Bank match:** which settlement most likely produced a bank entry.
- **Component closure:** whether every rupee inside that settlement has source
  evidence.
- **Conformance:** correctness on declared rule families.
- **OOD challenge:** post-generation mutations outside the normal fixture
  assumptions; still synthetic, not a production guarantee.
- **Journal proposal:** a balanced, unposted accounting suggestion.
- **Fail closed:** uncertainty becomes a review hold rather than an automatic
  financial action.
