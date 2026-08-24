# Metrics: dumb baseline

## Headline

| Metric | Value |
|---|---|
| records | 75 |
| coverage | 100.0% |
| match rate | 93.3% |
| match precision batch | 95.7% |
| match precision component | 100.0% |
| recall on resolvable | 93.1% |
| component recall on resolvable | 97.2% |
| false matches | 3 |
| false matches on unresolvable | 3 |
| misses | 5 |
| escalated | 5 |
| exception precision | 0.0% |
| unresolvable recall | 0.0% |

## Per tier

| Tier | n | Matched | Batch ok | Component ok | False | Miss | Refusal | Batch acc |
|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 6 | 6 | 6 | 0 | 0 | 0 | 100.0% |
| 1 | 21 | 21 | 21 | 21 | 0 | 0 | 0 | 100.0% |
| 2 | 34 | 34 | 34 | 34 | 0 | 0 | 0 | 100.0% |
| 3 | 11 | 6 | 6 | 6 | 0 | 5 | 0 | 54.5% |
| 4 | 3 | 3 | 0 | 0 | 3 | 0 | 0 | 0.0% |

## Calibration

| Confidence band | n | Mean confidence | Actual accuracy |
|---|---|---|---|
| 0.0-0.2 | 0 | n/a | n/a |
| 0.2-0.4 | 0 | n/a | n/a |
| 0.4-0.6 | 0 | n/a | n/a |
| 0.6-0.8 | 0 | n/a | n/a |
| 0.8-1.0 | 70 | 1.00 | 1.00 |
