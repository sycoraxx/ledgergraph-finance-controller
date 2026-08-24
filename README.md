# Finance Controller

Finance Controller explains where each Razorpay payout went.

It compares three sources—Razorpay settlements, a bank statement, and the
merchant cashbook—then:

1. matches the records that belong together;
2. checks that every rupee is explained;
3. sends uncertain or suspicious entries for review;
4. prepares balanced journal entries; and
5. waits for a person to approve them.

The demo uses simulated financial data only. It cannot move real money.

## The problem

A single bank payout may represent many payments, fees, refunds, and
adjustments. The reference text may be incomplete, dates may shift over a
weekend, and several records may have the same total. Finance teams often have
to compare gateway, bank, and accounting exports by hand.

Finance Controller turns that work into one review flow:

```text
Razorpay + bank + cashbook
            ↓
     find possible matches
            ↓
   choose one complete answer
            ↓
 safe journal entries + explained exceptions
            ↓
         human approval
```

## What makes it safe

- Code—not AI—calculates every amount and chooses every match.
- Money must balance exactly; nothing is silently rounded.
- One record cannot be used in two accepted matches.
- One-to-many, many-to-one, and many-to-many payouts are supported.
- Ties, incomplete searches, and unsupported components stop for review.
- Every exception includes timestamps and source-row citations.
- The local AI assistant is read-only: it explains checked evidence in plain
  language and cannot calculate, approve, post, or move money.
- Approved entries go only to a simulated ledger.

## What the demo shows

- 87 simulated bank entries across credits and debits
- realistic direct and grouped settlement shapes
- working-day timing, including Thursday T+2 landing on Monday
- suspicious entries with observed text, expected text, time, amount, and source
- human approval with locked financial fields
- an honest reliability page that separates known checks from new fraud patterns

The committed results are reproducible; the dashboard can also run a fresh
batch locally.

## Run it on Windows

Requirements: Git, Conda, Node.js 22+, PowerShell, and optionally an NVIDIA GPU.

```powershell
git clone https://github.com/sycoraxx/ledgergraph-finance-controller.git
cd ledgergraph-finance-controller
conda activate base
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
.\start-dashboard.ps1
```

Open [http://localhost:3000](http://localhost:3000).

The setup downloads the local Qwen model into `models/` and runs it on CUDA
when a compatible NVIDIA GPU is available. To skip the multi-gigabyte model:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -SkipModel
```

The complete controller still works without Qwen; only the conversational
wording changes to a safe deterministic fallback.

## Run the checks

```powershell
python -m unittest discover -v
python run.py
python -m eval.suite

cd web
corepack pnpm run lint
corepack pnpm run build
```

## Start here

- [Solution overview](SOLUTION_OVERVIEW.md) — the complete product in plain language
- [Five-minute demo](FIVE_MINUTE_DEMO.md) — exact clicks and narration
- [Local setup](LOCAL_SETUP.md) — detailed installation and troubleshooting
- [Technical reference](TECHNICAL_REFERENCE.md) — implementation and evaluation details
- [Data policy](DATA_POLICY.md) — why every financial record is simulated

## Scope

This is a safety-focused prototype, not production accounting or fraud software.
It does not use real bank or cashbook data, initiate payments, file journals to
a real ERP, or claim to catch every unknown fraud pattern. Those boundaries are
shown in the product and measured in the reliability tests.
