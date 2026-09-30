# Unrecognized-charge risk model

Run 2026-09-27T20:35:19, commit ab413e6, source data/lakehouse.duckdb. Algorithm: sklearn.HistGradientBoostingClassifier (LightGBM stand-in, TQ-022). fraud_score used: no.
Split by process_date: train 7625 rows (6 fraud), test from 2026-06-12: 4078 rows (3 fraud). Threshold chosen on the training split by cost (missed fraud x10, unnecessary verification x1).

## Gradient boosting (threshold 1.000)

| Split | n | Positives | Recall | Precision | Missed fraud | Unnecessary verifications | ROC AUC | PR AUC | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 7625 | 6 | 1.000 | 1.000 | 0 | 0 | 1.000 | 1.000 | 0 |
| test | 4078 | 3 | 0.000 | not defined | 3 | 0 | 0.624 | 0.001 | 30 |

## Rules baseline (threshold 1.000)

| Split | n | Positives | Recall | Precision | Missed fraud | Unnecessary verifications | ROC AUC | PR AUC | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 7625 | 6 | 0.000 | 0.000 | 6 | 4 | 0.410 | 0.001 | 64 |
| test | 4078 | 3 | 0.000 | 0.000 | 3 | 11 | 0.556 | 0.001 | 41 |

## Caveats

- Only 9 fraud rows in the source; the numbers are a pipeline check, not a result. Train on the full 2023 to 2026 history (TQ-013).
