# Post-freeze fraud holdout

Detector: `graphshield-v1-before-fresh-holdout` / `59526f93d4ab45e37f3c61f44d8f239945f8ce4413e8814dffbcd4ab95bedbe1`

The detector hash is enforced before evaluation. These mutation families were not used to modify the detector.
This remains a synthetic post-freeze test, not production fraud validation.

| Metric | Value |
|---|---|
| seed count | 5 |
| holdout records | 50 |
| holdout positive records | 35 |
| holdout negative records | 15 |
| true positives | 0 |
| false positives | 0 |
| false negatives | 35 |
| true negatives | 15 |
| precision | n/a |
| recall | 0.0% |
| recall 95 ci | ['0.0%', '9.9%'] |
| specificity | 100.0% |
| duration ms | 15837 |

## Results by frozen mutation family

- approver_velocity_burst: 0/15 dubious rows detected; recall 0.0%
- benign_uncommon_operating_path: 0/0 dubious rows detected; recall n/a
- coordinated_vendor_master_takeover: 0/5 dubious rows detected; recall 0.0%
- out_of_hours_approval: 0/5 dubious rows detected; recall 0.0%
- structured_split_payment: 0/10 dubious rows detected; recall 0.0%

This post-freeze partition tests new synthetic temporal, aggregate, and control-plane families without changing GraphShield. It is stronger than the known-miss replay but still does not estimate production fraud recall.
