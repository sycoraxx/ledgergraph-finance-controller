# Multi-seed closed-world conformance

5 varied seeds; 375 settlement records; 435 total bank entries; 55 planted dubious entries.

The controller never reads either reconciliation or risk ground truth during detection.

| Metric | Value |
|---|---|
| bank match precision | 100.0% |
| bank recall on resolvable | 100.0% |
| component closure precision | 100.0% |
| false auto closures | 0 |
| risk precision | 100.0% |
| risk recall | 100.0% |
| risk specificity | 100.0% |
| risk exact class accuracy | 100.0% |
| risk false positives | 0 |
| risk false negatives | 0 |
| safety gate passed | True |
| duration ms | 17393 |

## Per seed

| Seed | Settlements | Bank entries | Bank precision | Bank recall | Unsafe closes | Risk precision | Risk recall | FP | FN | ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260821 | 75 | 87 | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 0 | 0 | 3582 |
| 20260822 | 75 | 87 | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 0 | 0 | 3478 |
| 20260823 | 75 | 87 | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 0 | 0 | 3304 |
| 20260824 | 75 | 87 | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 0 | 0 | 3792 |
| 20260825 | 75 | 87 | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 0 | 0 | 3194 |
