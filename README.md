# Finance Controller

**Judges and first-time readers:** start with
[`HACKATHON_SUBMISSION.md`](HACKATHON_SUBMISSION.md) for the complete submission
brief or [`JUDGE_GUIDE.md`](JUDGE_GUIDE.md) for the three-minute demo.

Documentation: **[Hackathon submission](HACKATHON_SUBMISSION.md)** ·
**[Local setup](LOCAL_SETUP.md)** · **[Judge guide](JUDGE_GUIDE.md)** ·
**[Data policy](DATA_POLICY.md)**

An evidence-first Razorpay settlement controller. It reconciles bank credits to
settlement batches, verifies every payment/refund component against independent
exports, proposes balanced journals, and refuses to close unattributed money.

The local language model is a read-only Q&A router and explanation layer. It
does not calculate money, select matches, change approval thresholds, or post
anything. LangGraph owns the resumable workflow and human gate; deterministic
code remains the sole authority over every financial value.

## Reproduce the result

Python 3.10+ is the only dependency for the deterministic pipeline.

```bash
python run.py
python -m eval.suite
python -m unittest discover -v
```

`python run.py` executes one interactive 87-entry batch. The explicit
`python -m eval.suite` command runs the expensive multi-seed and mutation
partitions; dashboard runs never regenerate those offline datasets.

The current frozen seed produces 2,232 orders, 2,338 settlement-recon rows, 75
Razorpay settlement records, and 87 total bank entries. The bank statement has
79 credits and 8 debits. Nine entries are deliberately dubious: six credits and
three debits. Expected development-set results:

| Metric | Exact-UTR baseline | Controller |
|---|---:|---:|
| Bank recall | 8.0% | 100.0% |
| Bank precision | 100.0% | 100.0% |
| Component closure precision | 83.3% | 100.0% |
| Component-exception recall | 0.0% | 100.0% |
| False auto-closures | 1 | 0 |

The frozen bidirectional bank-risk fixture reports 100% precision and recall.
That number is deliberately labelled **closed-world conformance**: it proves the
detector implements the fixture's specified controls, not that novel fraud or
accounting anomalies will be detected.

These figures describe the committed synthetic distribution, not production
performance. The generator assumptions and known gaps are documented in
`generator/provenance.md`.

## Rigorous evaluation without a misleading 100% claim

The current-batch and offline entrypoints together execute six distinct evaluations:

1. the deliberately weak exact-UTR baseline;
2. settlement matching and component closure against controller-blind truth;
3. bidirectional bank-entry risk detection against separately written risk truth.
4. an eleven-case adversarial LedgerGraph suite comparing exact-reference,
   row-wise L0/L1, and global constraint reconciliation.
5. a known-miss GraphShield control replay whose scenario code lives outside
   the generator and detector;
6. a hash-locked post-freeze fraud holdout containing new temporal, aggregate,
   vendor-master, and out-of-hours mutation families.

## Scenario realism and evidence boundary

Every discrepancy shown in the dashboard is classified by
`agent/scenario_catalog.py`. The classification is explanatory metadata and
cannot change a reconciliation or risk decision.

| Badge | What it means | Typical evidence |
|---|---|---|
| Razorpay-native mechanic | A documented settlement lifecycle behavior reproduced with simulated money. | Razorpay settlement/reconciliation reports and bank posting data. |
| Cross-system integration failure | A plausible bank, ERP, export, or ETL discrepancy; not asserted to be caused by Razorpay. | Bank statement, gateway export, ERP and ingestion audit trail. |
| Adversarial stress case | A deliberately difficult graph topology used for solver coverage, not a frequency estimate. | Bank, settlement and treasury/netting evidence. |
| ERP control / fraud anomaly | A plausible control pattern that cannot be established from Razorpay alone. | ERP cashbook, approval history, vendor-master changes and invoice lineage. |

The balanced 13 / 12 / 12 / 13 LedgerGraph topology mix deliberately
over-samples grouped cases. A clean direct settlement feed is expected to be
dominated by 1:1 bank-to-settlement links. The other topologies demonstrate
bounded global reconciliation under aggregation, split posting, retry, or
netting assumptions; they are not production prevalence claims.

## LedgerGraph: the flagship reconciliation engine

The production path no longer chooses settlements one bank row at a time.
Bounded dynamic programming indexes signed subset totals and constructs a
canonical candidate graph across the full batch. OR-Tools CP-SAT then solves
the weighted set-packing problem over connected components. Controlled fuzzy
evidence—normalized UTRs, bounded edit distance, date windows, and amount
uniqueness—may generate or rank a candidate, but it can never override signed
money conservation. Every bank and settlement node may be selected at most
once. Only a proven optimum may proceed, and only edges mandatory across every
optimum are retained. Candidate truncation, a merely feasible solution,
timeout, ambiguity, and insufficient evidence all abstain.

The interactive 75-settlement fixture deliberately keeps `max_group_size=2`.
The same DP engine supports configured larger groups—the invariant tests include
a four-settlement aggregate—but group size remains a declared safety budget,
not an “arbitrary size” claim. Each DP total retains at most 64 witnesses and
the index at most 250,000 states. If either cap is reached, affected money-event
nodes are labelled incomplete and excluded from optimization.

The engine supports all four bounded reconciliation topologies: 1:1, one bank
entry to many settlements (1:N), many bank entries to one settlement (N:1),
and irreducible many-to-many groups (N:M). A grouped hypothesis is emitted only
when it cannot be decomposed into smaller money-conserving matches. Each atomic
selection emits one proof certificate and one human-gated journal proposal.

The flagship batch deliberately avoids a token “one example each” demo. Its 75
bank and 75 settlement nodes resolve into 50 atomic groups: **13 × 1:1, 12 ×
1:N, 12 × N:1, and 13 × N:M**. Split ratios vary by group, and every N:M group
is checked for irreducibility so a disguised smaller match is rejected.

The pre-solve mesh is intentionally adversarial rather than pre-cleaned: **473
candidate hyperedges compete for those 50 selections**. It includes 80 1:N, 91
N:1, and 92 N:M hypotheses. Hard gates reject 68 / 67 / 59 grouped candidates
respectively; the global one-use objective rejects another 12 N:1 and 20 N:M
exact-money alternatives. Thus a rejected edge can mean either “accounting
invariant failed” or “locally plausible, but incompatible with the best complete
batch explanation”—the dashboard labels those two cases separately.

`settlement_schedule.csv` is the canonical synthetic timing ledger. It mixes 33
T+1 and 42 T+2 settlements under a Monday-Friday business-day policy, verifies
capture ≤ settlement ≤ bank posting, and includes 11 Thursday T+2 → Monday proof
cases. This policy is an explicit simulation assumption—not a claim that every
Razorpay merchant has the same settlement contract.

On the committed eleven-case synthetic adversarial suite:

| System | Exact cases | Hypothesis recall | Selection precision | False selections |
|---|---:|---:|---:|---:|
| Exact-reference baseline | 5/11 | 33.3% | 100.0% | 0 |
| Row-wise L0/L1 | 6/11 | 55.6% | 83.3% | 1 |
| LedgerGraph global | 11/11 | 100.0% | 100.0% | 0 |

Four cases form the calibration partition used to select threshold 65; the
frozen seven-case held-out partition scores 7/7 with zero false selections. These
are declared synthetic reconciliation cases, not evidence of production fraud
performance, and confidence values are policy bands—not empirical probabilities.

The five-seed, 435-entry robustness run is an invariant/conformance suite. It
checks that changes in amounts, references, and dates do not break the declared
rules. It is useful regression evidence, but it is not called generalization or
production performance.

The separate mutation challenge covers 440 entries across five seeds. It adds a
benign posting delay, balance tampering, counterparty substitution, and a
duplicate backed by apparently valid but collusive approval evidence. Exact
controls alone remain frozen at 100.0% precision and 84.4% recall. GraphShield,
an explainable relational open-set layer, inspects counterparty identity edges,
approver support, repeated economic motifs, and reference fan-out after
reconciliation. On the same replay it recovers the ten previous misses with no
additional false positives. That 100.0% result is labelled **known-miss control
replay**, not validation.

The separate post-freeze partition locks the SHA-256 of the unchanged
GraphShield source before evaluation. Across five seeds it contains 35 dubious
rows from four new families and 15 clean hard negatives. Current GraphShield
detects **0/35 (0.0% recall)** with **100.0% specificity**. Those 35 misses are
the honest result: the detector has no temporal velocity, cross-event aggregate,
independent vendor-master, or operating-hours evidence. The suite remains
synthetic and still does not estimate production fraud performance.

The risk benchmark includes duplicate references, amount mismatches, unsupported
transactions, and unattributed settlement components. Credits and debits are
reported separately. Each finding contains plain-language observed evidence,
the expected independent evidence, transaction and extraction timestamps,
severity, recommended action, and exact source-row citations.

The detector reads `bank_statement.csv`, Razorpay-shaped exports, and the
independent ERP `cashbook.csv`. It never reads `ground_truth.json` or
`risk_truth.json`; those files are opened only by evaluation after predictions
have been persisted.

## Run the local control room

The complete Windows setup is documented in [`LOCAL_SETUP.md`](LOCAL_SETUP.md).
With Conda base active, the recommended installer pins dependencies, downloads
the checksum-verified local model/runtime, and runs the verification gates:

```powershell
conda activate base
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
.\start-dashboard.ps1
```

Manual installation is also supported:

```powershell
conda activate base
python -m pip install -r requirements.txt
python scripts\download_local_model.py
cd web
corepack pnpm install --frozen-lockfile
```

On Windows, the launcher starts the local CUDA model server, API, and frontend.
It discovers system pnpm, Corepack, or the Node runtime bundled with Codex:

```powershell
.\start-dashboard.ps1
```

You can run this from inside `web/` with `..\start-dashboard.ps1`. Press
`Ctrl+C` to stop all local services. If your PowerShell execution policy blocks a
local script, use `..\start-dashboard.cmd` instead.

Alternatively, start the API and dashboard in two terminals:

```powershell
# terminal 1
python -m uvicorn dashboard.api:app --host 127.0.0.1 --port 8000

# terminal 2 (frontend; Qwen is optional for deterministic results)
cd web
corepack pnpm run dev
```

Open `http://localhost:3000`. The control room can run the complete batch,
inspect exact exception citations, query deterministic evidence, and resume a
human approval interrupt. An approval writes only to the local idempotent
sandbox ledger in `results/demo_ledger.sqlite`; it never calls Razorpay or a
real accounting system from the approval/posting path. The separate source
adapter below can perform allowlisted read-only Razorpay Test Mode fetches.

## Connect Razorpay's hosted simulated Test Mode API feed

This project has a read-only adapter for Razorpay's hosted Test Mode API. The
transport and schemas are operated by Razorpay, but all Test Mode entities and
money are simulated. It accepts only
Test Mode keys (`rzp_test_...`) and only calls allowlisted `GET` endpoints for
orders, payments, refunds, settlements, and settlement recon. Live keys are
blocked, the secret is never returned to the browser or written to disk, and no
money-changing endpoint exists in the connector.

1. Create a Razorpay account using the official quickstart:
   <https://razorpay.com/docs/payments/quickstart/>. Test Mode can be used while
   onboarding/KYC is in progress; it does not move real customer money.
2. In the Razorpay Dashboard, select **Test Mode**.
3. Open **Account & Settings → API Keys** under Website and app settings, then
   choose **Generate Key**. Save the secret immediately; Razorpay shows it only
   when it is generated. Official key instructions:
   <https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/>.
4. Copy `.env.example` to `.env` and enter the Test Mode values:

   ```dotenv
   RAZORPAY_KEY_ID=rzp_test_...
   RAZORPAY_KEY_SECRET=...
   ```

5. Restart `start-dashboard.cmd`, then click **Sync API feed** in the Source
   manifest card. Alternatively, from Conda base run:

   ```powershell
   python -m integrations.razorpay_feed
   ```

Snapshots are written under `data/razorpay_api/snapshots/<timestamp>/`. Each
contains untouched API JSON, normalized CSVs, hashes, extraction time, and the
31-day coverage window. Credentials are excluded from every artifact.

An empty new Test Mode account may correctly return zero rows until test orders
and payments exist. The sync is still proof of authenticated connectivity.

Important boundary: this proves compatibility with Razorpay's hosted Test Mode
API, not contact with real financial data. The bank statement is a disclosed
simulated bank emulator and the cashbook is a disclosed simulated merchant ERP
fixture. Real bank, ERP, customer, vendor, or Live Mode data is prohibited by
the project policy in `DATA_POLICY.md`.

## Architecture and authority boundary

```text
LangGraph StateGraph + durable SQLite checkpoints
           |
           v
 validate source hashes and official-schema-shaped CSVs
           |
           v
 deterministic LedgerGraph global reconciliation
           |
           +---- GraphShield relational risk <---- independent ERP cashbook
           |
           v
 cross-source component verification -> unresolved => exception
           |
           v
 ground-truth evaluation + measured proof bundle
           |
           v
 balanced journal proposal
           |
           v
 LangGraph interrupt -> human approve/reject -> sandbox ledger
           |
           +---- read-only evidence store <---- Qwen 3.5 4B Q&A
```

Graph nodes are deliberately coarse-grained: the deterministic engine processes
the full batch inside one node instead of checkpointing every CSV row. Approval
runs as a separate durable graph so pausing and resuming cannot accidentally
re-execute a posting side effect.

The controller distinguishes two outcomes that must not be conflated:

1. **Bank match:** which settlement produced a bank entry?
2. **Component closure:** can every rupee be attributed to a payment, refund,
   fee, tax, dispute, or supported adjustment?

A settlement can therefore be correctly matched while still being refused for
posting because one component is unattributed.

GraphShield adds a third, non-authoritative question: even when the accounting
path balances, is the surrounding identity/approval motif unfamiliar? It never
changes a LedgerGraph match or money value. A score over the review threshold
only escalates the entry to a human.

## Project-local Qwen on a 4 GB RTX 3050

The application uses a Q4_K_M GGUF quantization of Qwen 3.5 4B downloaded from
Hugging Face and a pinned CUDA build of `llama.cpp`. The weights live under
`models/qwen3.5-4b/` inside this project instead of Ollama's global store. The
selected checkpoint is about 2.55 GiB, leaving room for a 4,096-token context
and runtime buffers on a 4 GB laptop GPU.

The base checkpoint is the official Apache-2.0 Qwen model. The GGUF is a
community quantization published by Unsloth, not an official Qwen GGUF; its
exact file hash is pinned in the downloader. The launcher requires `CUDA0`,
requests every layer on the GPU, disables automatic CPU fallback, and fails at
startup if that allocation cannot be satisfied. It uses one inference slot,
which avoids reserving memory for concurrency that a single-user demo does not
need.

```powershell
conda activate base
python -m pip install -r requirements.txt
python scripts\download_local_model.py
.\start-dashboard.ps1
```

The downloader verifies the model and runtime archives against pinned SHA-256
checksums. The launcher starts Qwen on port 8001, the controller API on port
8000, and the web UI on port 3000, then stops all three together.

To exercise the model from another terminal while the dashboard is running:

```powershell
python -m agent.qa "Why was BNK000004 held for review?"
python -m agent.qa "List the unresolved exceptions"
python -m eval.qa_eval
```

The client defaults to `http://127.0.0.1:8001/v1` and model
`qwen3.5-4b-q4_k_m`. Override them when needed:

```powershell
$env:FINCTRL_MODEL_URL = "http://127.0.0.1:8001/v1"
$env:FINCTRL_MODEL = "qwen3.5-4b-q4_k_m"
```

Without a running model, identifier-based questions safely fall back to the
same read-only tools and return their evidence verbatim:

```bash
python -m agent.qa "Why was BNK000004 held?" --no-model
```

`python -m eval.qa_eval` runs 55 in-domain routing cases, including prompt-injection
attempts, and writes schema-valid rate, correct-tool rate, exact-argument rate,
and forbidden-call counts to `results/qa_metrics.md`. This measures the exact
quantized model and serving stack used in the demo rather than borrowing a
generic leaderboard score.

## Safety properties

- The model can access four allowlisted read-only tools.
- Tool arguments are checked against strict schemas and identifier formats.
- A malformed or forbidden call is rejected and audited.
- Money is represented with `Decimal`, never binary floating point.
- Exact UTR matches also require exact amount agreement.
- Amount collisions fail closed unless deterministic evidence uniquely breaks
  the tie.
- Fuzzy evidence can rank candidates but cannot relax exact signed-money
  conservation.
- Split/merge matches are bounded and globally constrained; DP truncation,
  unproven CP-SAT status, and tied optimal edges abstain.
- Journal proposal IDs are deterministic, making reruns idempotent.
- Every journal must balance before it reaches the approval policy.
- The approval node accepts only `approve` or `reject`; amounts are immutable.
- The sandbox ledger has a unique key on `proposal_id`, so retries cannot
  duplicate a posting.
- No code path calls a real ledger, Razorpay money API, or moves money.

## Important artifacts

- `results/agent/metrics.md` — controller metrics.
- `results/agent/exceptions.md` — honest review queue.
- `results/risk/risk_metrics.md` — credit/debit precision, recall, costs, and class breakdown.
- `results/risk_findings.json` — auditor-readable dubious-entry evidence.
- `results/graph_ood_summary.json` — evidence-graph topology, signals, and authority boundary.
- `results/graph_ood_assessments.json` — per-entry relational nonconformity features and paths.
- `results/robustness/robustness_metrics.md` — five-seed full-pipeline evaluation.
- `results/challenge/challenge_metrics.md` — known-miss regression replay and confidence interval; not a fresh validation set.
- `results/challenge/mutation_manifest.json` — exact post-generation changes applied by the challenge.
- `results/ledgergraph/ledgergraph_metrics.md` — adversarial comparison with row-wise baselines.
- `results/ledgergraph/proof_certificates.json` — 1:1, 1:N, N:1, and N:M proof certificates.
- `results/ledgergraph.json` — primary batch candidate graph and global solution.
- `results/journal_proposals.json` — balanced, unposted proposals.
- `results/audit.jsonl` — deterministic decision trail.
- `results/qa_audit.jsonl` — accepted/rejected model calls.
- `results/workflow_checkpoints.sqlite` — local LangGraph checkpoints (generated).
- `results/demo_ledger.sqlite` — idempotent local sandbox postings (generated).
- `generator/schemas/` — CSV conversions of official Razorpay sample reports.
- `data/ground_truth.json` — hidden-from-controller benchmark truth.
- `data/risk_truth.json` — hidden-from-detector credit/debit labels.
- `data/provenance.json` — extraction time, coverage window, seed, and source roles.
- `integrations/razorpay_feed.py` — read-only hosted Test Mode API adapter.
- `data/razorpay_api/latest.json` — latest hosted Test Mode snapshot metadata (generated, ignored).
- `DATA_POLICY.md` — simulation-only data boundary and prohibited sources.

## Repository layout

- `generator/` — seeded forward simulator, provenance, and official samples.
- `agent/` — deterministic matcher, verifier, policy, journal, LangGraph, and Q&A.
- `dashboard/` — local FastAPI surface for runs, Q&A, and approval interrupts.
- `web/` — responsive settlement control-room frontend.
- `eval/` — deliberately weak baseline and ground-truth scorer.
- `tests/` — financial invariants and fail-closed adversarial cases.
- `results/` — reproducible predictions, metrics, exceptions, and audit logs.
