# Five-minute demo

This walkthrough is self-contained. A viewer does not need to know the code,
graph theory, or machine learning terminology.

## Before recording

1. Run `python scripts/start.py` and open `http://localhost:3000`.
2. Confirm the top-left status says **Controller ready**.
3. If configured, confirm the assistant says **AI explanations on**.
4. Keep `BNK000015` in the question box.
5. Start on **Home** at 100% browser zoom.

If the optional AI is unavailable, continue the recording. Built-in mode
returns the same checked evidence without conversational rewriting.

## 0:00–0:35 — the problem

**Show:** Home hero and the three-source diagram.

**Say:**

> A Razorpay payout reaches the bank as one number, but that number may contain
> many payments, refunds, fees, and adjustments. The finance team then has to
> compare the Razorpay report, bank statement, and cashbook. Finance Controller
> turns those three views into one explainable, review-ready answer.

## 0:35–1:10 — the result

**Show:** The four large metrics and extraction timestamps. Click **Run current
batch** only if you want to demonstrate the live pipeline.

**Say:**

> This is a fully simulated batch, so no real financial data or money is at
> risk. The controller checks every bank credit and debit, prepares safe journal
> entries, and stops uncertain items. Notice that zero entries are posted
> automatically. The extraction time and coverage window are always visible.

## 1:10–2:15 — why reconciliation is hard

**Click:** **Match**. Keep **Messy view** selected, then switch to
**Accepted view**.

**Say:**

> This messy mesh is the real problem. Several settlements may plausibly explain
> the same bank entry, and a payout can be one-to-one, one-to-many, many-to-one,
> or many-to-many. The controller considers the whole batch together. The
> accepted view keeps one conflict-free answer: money balances exactly, dates
> and references support it, and no record is reused. If the search is incomplete
> or two answers tie, it stops instead of guessing.

**Show:** “Three checks, in plain language.”

> The rule is easy to remember: exact money, supporting details, and one complete
> answer for the batch. Settlement dates use business days, so Thursday T+2 is
> Monday, not Saturday.

## 2:15–3:10 — investigate an exception

**Click:** **Review**, then open `BNK000015`.

**Say:**

> Reconciliation alone is not enough—a balanced payout may still contain an
> unsupported component. This entry is stopped because the adjustment does not
> have an attributable source record. The reviewer sees the direction, amount,
> observed and expected text, transaction time, extraction time, and exact CSV
> rows. This is an actionable exception, not just an anomaly score.

Close the detail panel.

## 3:10–3:50 — ask the evidence

**Click:** **Home**. Ask: `Why was BNK000015 held for review?`

**Say:**

> The optional AI assistant turns the checked result into a plain answer. It can
> run through a hosted API or locally, and receives only read-only evidence. It
> does not route the question, calculate money, choose matches, change journals,
> or approve anything. If it is offline, the controller returns the same facts
> directly.

## 3:50–4:30 — human approval

**Click:** **Approve**, then open any pending proposal.

**Say:**

> For a safe match, code prepares the journal entry and checks that debits equal
> credits. The financial fields are locked. A person can inspect the evidence
> and approve or reject. Even approval records only to this simulated ledger,
> and retrying cannot post the same proposal twice.

Do not approve during the main take unless you have rehearsed the state change.

## 4:30–4:55 — honest reliability

**Click:** **Controls**.

**Say:**

> I separate three claims. Known rules prove the implementation works. Previous
> mistakes prove regressions stay fixed. A frozen test with new fraud patterns
> measures generalization—and the misses stay visible. This is not a fake 100%
> fraud claim; it is an honest picture of what works and what still needs more
> evidence.

## 4:55–5:00 — close

**Say:**

> Finance Controller explains the money, isolates uncertainty, and keeps a human
> in control. That is how AI can help run finance operations safely.

## One-line answers for likely questions

- **Why use a graph?** Because several records can belong to one payout and all
  possible matches must be resolved together, not row by row.
- **Why use AI at all?** To make checked evidence easy to ask about and explain;
  deterministic code remains the financial authority.
- **Is this real data?** No. Every financial record is simulated, including the
  bank statement and cashbook.
- **Can it post real money?** No. The connector is read-only Test Mode, and the
  ledger is simulated.
- **Does it catch every fraud?** No. The Controls page shows the current
  misses on new synthetic fraud patterns.
