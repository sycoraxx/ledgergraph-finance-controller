# Provenance of generator values

Every constant in `generate.py` is either verified against a source or invented.
This file says which. Anything marked invented must not be presented as
realistic without checking it first.

## Verified

| Value | Setting | Source |
|---|---|---|
| Settlement cycle T+2 working days | `add_working_days(d, 2)` | Razorpay docs, settlements FAQ |
| Working days exclude Sundays, bank holidays, 2nd and 4th Saturdays | `is_working_day` | Razorpay docs, settlements FAQ |
| GST at 18% on the gateway fee, not on transaction value | `GST_RATE` | Razorpay pricing blog |
| UPI carries zero MDR but a platform fee still applies | `RATE_CARD["upi"]` | Razorpay / SmartBiz fee help article |
| Platform fee on UPI maps to the standard ~2% rate | `RATE_CARD["upi"] = 0.0200` | Razorpay pricing coverage, May 2026 |
| Credit card MDR 1.8–2.5%, premium and corporate at the top | `card_credit`, `card_premium` | Razorpay transparent-pricing blog |
| Debit card MDR 0.9–1.5% | `card_debit = 0.0120` | Razorpay transparent-pricing blog |
| International card MDR 3–4.5% | `card_intl = 0.0350` | Razorpay pricing blog |
| Flat per-refund fee of ₹3–5 | `REFUND_FEE = 4.00` | Fee coverage, refund charges since 2024 |
| Recon report column names, all 27 | `write()` | `sample-settlements-recon-report.xlsx` |
| Payment rows: credit is net of fee; refund rows: amount sits in debit | `write()` | Same sample file, rows 0 and 4 |
| Recon report carries dispute_id / dispute_created_at / dispute_reason | Dispute entity | Same sample file, header row |
| Refund rows carry an `arn`, payment rows do not | `write()` | Sample recon + refunds reports |
| Timestamps mix ISO, dd/mm/yyyy and Excel serial in one column | `DateWriter` | Sample recon report, `entity_created_at` |

## Invented, and nothing depends on them

| Value | Note |
|---|---|
| `ISSUERS` | IFSC-style bank codes. Cosmetic. No matching logic reads `issuer_name`. |
| `DISPUTE_REASONS` | Plausible but unverified. Check Razorpay's disputes docs before claiming these are real reason codes. |
| Customer IDs, receipt numbers, email and contact fields | Filler. |
| Bank narration template | Modelled on Indian NEFT narration shape, not copied from a real statement. |
| Opening bank balance of 250,000 | Arbitrary. |
| ERP cashbook counterparties and purposes | Synthetic labels used only to make review evidence readable. |
| Bank-entry extraction timestamp | The actual UTC time at which the synthetic files were generated, not a production-system extraction. |

## Invented, and load-bearing — treat with care

| Value | Note |
|---|---|
| The specific rates in `RATE_CARD` | Real rate cards are negotiated per merchant, blended or split. These sit inside published ranges but are one plausible card, not the card. The agent must infer effective rates from settlement history, never hardcode these. |
| Refund rate of 4.5%, dispute rate of 0.8% of card payments | Plausible order of magnitude, not sourced. If a judge asks, say so. |
| Method mix (55% UPI, 30% card, 10% netbanking, 5% wallet) | Reflects the general Indian shift toward UPI. Not from a specific dataset. |
| Premium card share of 15% of credit cards, international share of 3% | Invented. |
| Tier proportions | Chosen to make the difficulty curve useful, not to mirror a real merchant. This is the biggest single assumption in the project and belongs in the limitations slide. |
| Duplicate, amount-mismatch and unsupported credit/debit frequencies | Deliberately balanced evaluation augmentations. They test controls; they do not estimate production prevalence. |

## Bidirectional bank-risk benchmark

The bank statement now includes both Razorpay settlement activity and operating
cashbook activity. An independent `cashbook.csv` is generated before risk
detection. The bank export then receives controlled augmentations in both
directions:

- duplicate approved references for one credit and one debit;
- amount mismatches against one approved credit and one approved debit;
- one unsupported credit and one unsupported debit;
- unattributed settlement adjustments inherited from the reconciliation tiers.

`risk_truth.json` records the planted labels, but the detector never reads it.
The file is consumed only after `risk_assessments.json` has been written. The
unit suite also removes the truth file and proves that detection results remain
unchanged.

Amounts vary by seed. Five default holdout seeds therefore exercise different
payments, settlements, cashbook amounts, references, and component-exception
counts while preserving the declared anomaly classes.

## Extraction and coverage timestamps

`provenance.json` records the generation/extraction timestamp in UTC, the data
coverage start and end dates, the seed, source-system label, row count, and
controller-blind status of evaluation truth. `bank_statement.csv` and
`cashbook.csv` also carry transaction timestamps. The LangGraph source manifest
adds file modification time and SHA-256 so an auditor can distinguish when the
underlying activity occurred, when the bundle was extracted, and when the
controller evaluated it.

## Determinism

The generator uses six independent RNG streams derived from the master seed:
volume, payment, refund, dispute, batch and render. This is deliberate.

With a single shared stream, adding one draw anywhere shifts every subsequent
value, so an unrelated change to payment logic silently alters how many orders
each day produces. That makes it impossible to freeze the dataset and compare
eval runs across days, because you can never tell whether a score moved because
the agent improved or because the data changed underneath it.

Test for this after any generator edit: change a probability in one stage and
confirm the record counts from the other stages do not move.

## Known gaps, not yet modelled

- On-demand and same-day instant settlements, which appear as payouts in the
  report rather than settlements and are a double-counting trap.
- Multiple balance accounts (online, in-person POS, international), which the
  newer recon report separates by `channel_type` and `balance_account`.
- TDS under section 194-O and reconciliation against Form 26AS.
- Settlements placed on hold.
- COD orders settled through a courier remittance file rather than the gateway.
