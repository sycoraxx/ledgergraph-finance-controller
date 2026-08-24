# Bidirectional bank-risk closed-world conformance

Ground truth is generated before detection and is never read by the detector.

| Metric | Value |
|---|---|
| records | 87 |
| dubious records | 9 |
| clean records | 78 |
| true positives | 9 |
| true negatives | 78 |
| false positives | 0 |
| false negatives | 0 |
| precision | 100.0% |
| recall | 100.0% |
| specificity | 100.0% |
| f1 | 100.0% |
| exact anomaly class accuracy | 100.0% |
| false negative exposure inr | 0.00 |
| false positive review value inr | 0.00 |
| safety gate passed | True |

## Direction breakdown

| Direction | Records | Dubious | Precision | Recall | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| credit | 79 | 6 | 100.0% | 100.0% | 0 | 0 |
| debit | 8 | 3 | 100.0% | 100.0% | 0 | 0 |

## Anomaly-class breakdown

| Class | n | Detected | Exact class | Recall | Class accuracy |
|---|---:|---:|---:|---:|---:|
| amount_mismatch | 2 | 2 | 2 | 100.0% | 100.0% |
| duplicate_reference | 2 | 2 | 2 | 100.0% | 100.0% |
| unattributed_settlement_component | 3 | 3 | 3 | 100.0% | 100.0% |
| unsupported_transaction | 2 | 2 | 2 | 100.0% | 100.0% |
