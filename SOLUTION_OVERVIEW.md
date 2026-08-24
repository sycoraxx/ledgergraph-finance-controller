# Finance Controller: solution overview

## One-sentence description

Finance Controller compares Razorpay, bank, and cashbook records, explains each
payout, stops uncertain entries, and prepares journal entries for human approval.

## Who it is for

A finance or operations team that receives payment-gateway settlements and must
record them in its books.

## Why this is difficult

The bank shows a payout as one number. The payment gateway may explain that
number using dozens of payments, refunds, fees, and adjustments. The cashbook is
a third view of the same activity. Dates can move over weekends, references can
contain small text errors, and several different groups can have the same total.

Matching one row at a time can therefore create a locally plausible but globally
wrong answer.

## The complete workflow

### 1. Collect

The demo loads three simulated sources:

- Razorpay-style payment and settlement records;
- bank credits, debits, timestamps, balances, and narrations; and
- merchant cashbook records and approvals.

The extraction time and coverage window remain visible in the dashboard.

### 2. Reconcile

The controller finds all reasonable direct and grouped matches. It supports one
bank entry to one settlement, one to many, many to one, and many to many.

It then chooses one complete answer for the batch. Every accepted group must:

- balance to the exact paisa;
- have supporting date or reference evidence;
- obey the configured business-day timing; and
- avoid reusing any bank or settlement record.

If the search is incomplete or two answers are tied, the affected records stop
for review.

### 3. Check risk

Balanced money can still be suspicious. The controller therefore checks both
credits and debits for issues such as an unsupported adjustment, a beneficiary
name that disagrees with the cashbook, a missing or reused reference, duplicate
activity, or an unusual approval pattern.

Each finding says what was observed, what was expected, when it happened, how
much is affected, and which source rows support the conclusion.

### 4. Prepare the books

For safe reconciliations, deterministic code creates a balanced journal proposal.
Financial fields are locked. The system cannot post the proposal by itself.

### 5. Approve and audit

A reviewer can inspect the source evidence and approve or reject. Approved demo
entries are recorded in a simulated ledger. Every system and human action is
kept in a timestamped activity trail, and retrying the same approval cannot
create a duplicate posting.

## Where AI helps

The local Qwen model is an explanation assistant. It receives a checked evidence
object and turns it into a readable answer such as “Why was BNK000015 held?”

It cannot:

- choose a match;
- calculate an amount;
- change a journal;
- approve a decision;
- post an entry; or
- move money.

This separation lets a small local model improve usability without becoming a
financial authority.

## What makes the demo credible

- The batch has more than 50 records and covers credits and debits.
- Grouped settlement shapes are deliberately balanced for test coverage.
- Dates follow working-day rules, including a Thursday T+2 settlement on Monday.
- Possible matches and rejected alternatives are visible in the graph.
- New fraud-pattern tests are kept separate from cases used to design the checks.
- Misses on new patterns remain visible; no 100% production-fraud claim is made.
- All data and all postings are simulated.

## Product promise

Finance Controller does not promise that AI will run the books. It promises a
clearer and safer finance workflow: explain the money, isolate uncertainty, give
the reviewer the evidence, and never act beyond the reviewer’s authority.
