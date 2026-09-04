# Business Operations Guide

This runbook describes a controlled Finance Controller pilot using simulated
records. It is written for finance operators, reviewers, and system owners.

## Roles

| Role | Responsibility | Must not do |
| --- | --- | --- |
| Finance operator | Load a batch, run reconciliation, investigate exceptions | Change generated amounts or approve their own unresolved work |
| Journal reviewer | Compare a proposal with its cited evidence and approve/reject | Treat a model explanation as source evidence |
| System owner | Manage releases, secrets, access, backups, and monitoring | Give the AI provider write access |
| Auditor | Inspect provenance, decisions, exceptions, and control results | Edit historical events |

One person may fill multiple roles in this simulation. A business deployment
should enforce separation of duties based on its materiality policy.

## Daily procedure

1. Confirm the **extraction timestamp** and **coverage window** on Home.
2. Confirm that all expected sources are present and their row counts are
   plausible.
3. Select **Run current batch**. Do not close the browser while the batch is
   running.
4. On Match, confirm whether the whole-batch answer is complete. Search-limit,
   tie, or incomplete statuses are review conditions—not successful matches.
5. On Review, investigate every entry. Compare bank text, expected text, time,
   amount, and cited rows. Record the decision outside this prototype if the
   business requires a ticket or case identifier.
6. On Approve, inspect the bank group, settlement group, every debit/credit
   line, and the balance check. Approve or reject; do not infer approval from an
   AI explanation.
7. On History, confirm that the run and human decisions appear with timestamps.
8. On Controls, review any change in test performance or disclosed blind spots
   before adopting a new release.

## Acceptance criteria for a batch

A batch may be considered complete only when:

- all required source files passed validation;
- candidate generation reports complete for every auto-closed component;
- each selected group conserves signed money exactly;
- no source record is reused across selected groups;
- every tied, incomplete, unsupported, or suspicious record is held for review;
- journal debits equal credits;
- every recorded journal has a named human reviewer and timestamp; and
- the exception count and unresolved value have been acknowledged.

An exception is a controlled outcome. Never change a rule merely to reduce the
exception count for the current batch.

## Source handling

The included data is synthetic. If a future pilot introduces business data:

- land immutable source snapshots in encrypted storage;
- record source system, tenant, extraction time, coverage window, schema
  version, row count, and checksum;
- quarantine unexpected schemas rather than coercing them silently;
- restrict operator access to the minimum required records;
- define retention and deletion schedules; and
- keep provider keys and source credentials in a managed secret store.

Do not send business data to a hosted AI provider until legal, security, privacy,
and vendor reviews have approved the exact data flow. The model is optional.

### Large declared groups

For an aggregate containing many rows, export one dedicated membership field on
both sides: `reconciliation_group_id`, `payout_id`, or `batch_id`. Use the same
field name and value for every member of that accounting scope. Do not place a
free-text bank narration into these fields.

The controller reserves all records carrying the key for that group. If the
other source is missing, the total does not balance, chronology fails, or either
side exceeds 1,000 records, the whole declared group is held. It is not silently
rematched against unrelated records. Unknown memberships over the bounded
inference budget are also review conditions.

## Incident procedure

Stop the batch and preserve its inputs and outputs if any of these occurs:

- a selected match has a non-zero residual;
- the same source record appears in two accepted groups;
- a journal is recorded without a human decision;
- an extraction timestamp or checksum is missing;
- the candidate search is reported incomplete but the record is auto-closed;
- results change when the same immutable batch is rerun; or
- a real/live Razorpay key is presented to this project.

Capture the batch fingerprint, application version/commit, timestamps, logs, and
affected record IDs. Reproduce with the same input snapshot. Do not overwrite the
original evidence while investigating.

## Change and release control

For each release:

1. review rule and schema changes with a finance owner;
2. run `python -m unittest discover -v`;
3. run `python -m eval.suite` without modifying the frozen holdout;
4. run frontend lint and build;
5. compare exception, false-positive, and false-negative counts with the prior
   release;
6. record the commit and test artifacts; and
7. require reviewer sign-off before promoting the release.

Test metrics over synthetic data are engineering evidence, not a service-level
guarantee or a claim of production fraud coverage.

## Backup and recovery for a pilot

Persist and back up the `results/` directory after each accepted batch. It holds
workflow state, audit artifacts, and the simulation ledger. Test restoration on
a separate environment. SQLite supports a single-instance pilot; use a managed
transactional database before horizontal scaling or multi-tenant operation.
