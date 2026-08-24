# Known-miss control replay

This suite mutates generated exports after generation, but GraphShield's features were informed by these misses.
Intervals describe this synthetic challenge only and are not production confidence bounds.

| Metric | Value |
|---|---|
| seed count | 5 |
| bank entries | 440 |
| mutations | 20 |
| true positives | 64 |
| true negatives | 376 |
| false positives | 0 |
| false negatives | 0 |
| precision | 100.0% |
| precision 95 ci | ['94.3%', '100.0%'] |
| recall | 100.0% |
| recall 95 ci | ['94.3%', '100.0%'] |
| specificity | 100.0% |
| false negative exposure inr | 0.00 |
| false positive review value inr | 0.00 |
| duration ms | 15988 |

## Before/after graph intelligence

- deterministic controls: recall 84.4%, false negatives 10
- GraphShield: recall 100.0%, false negatives 0, additional false positives 0

## Known misses


GraphShield closes the two declared identity/motif gaps in this synthetic replay. Its features were designed after analysis of these misses, so this is regression evidence only—not validation on unseen fraud families.

## Mutations

- seed 20260831 · BNK000004 · benign_one_day_posting_lag · truth=clean
- seed 20260831 · BNK000007 · counterparty_substitution · truth=dubious
- seed 20260831 · BNK000021 · balance_tamper · truth=dubious
- seed 20260831 · BNK900000 · collusive_duplicate · truth=dubious
- seed 20260832 · BNK000004 · benign_one_day_posting_lag · truth=clean
- seed 20260832 · BNK000007 · counterparty_substitution · truth=dubious
- seed 20260832 · BNK000021 · balance_tamper · truth=dubious
- seed 20260832 · BNK900000 · collusive_duplicate · truth=dubious
- seed 20260833 · BNK000004 · benign_one_day_posting_lag · truth=clean
- seed 20260833 · BNK000007 · counterparty_substitution · truth=dubious
- seed 20260833 · BNK000021 · balance_tamper · truth=dubious
- seed 20260833 · BNK900000 · collusive_duplicate · truth=dubious
- seed 20260834 · BNK000004 · benign_one_day_posting_lag · truth=clean
- seed 20260834 · BNK000007 · counterparty_substitution · truth=dubious
- seed 20260834 · BNK000021 · balance_tamper · truth=dubious
- seed 20260834 · BNK900000 · collusive_duplicate · truth=dubious
- seed 20260835 · BNK000004 · benign_one_day_posting_lag · truth=clean
- seed 20260835 · BNK000007 · counterparty_substitution · truth=dubious
- seed 20260835 · BNK000021 · balance_tamper · truth=dubious
- seed 20260835 · BNK900000 · collusive_duplicate · truth=dubious
