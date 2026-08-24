# LedgerGraph adversarial evaluation

All records are synthetic. This evaluates reconciliation structure—not production fraud detection.

| System | Exact cases | Hypothesis recall | Selection precision | False selections |
|---|---:|---:|---:|---:|
| exact_reference_baseline | 5/11 | 33.3% | 100.0% | 0 |
| rowwise_l0_l1 | 6/11 | 55.6% | 83.3% | 1 |
| ledgergraph_global | 11/11 | 100.0% | 100.0% | 0 |

- Selection threshold: 65.
- Threshold rule: lowest tested threshold with zero false selections on the four-case calibration partition.
- Held-out cases exact: 7/7 with 0 false selections.
- Grouped topology cases correct: 3/3.
- Selected certificate residual failures: 0.
