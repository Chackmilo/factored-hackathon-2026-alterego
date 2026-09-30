# Unrecognized-charge risk model

Run 2026-09-28T04:28:13, commit 6f0297e, source data/lakehouse_full.duckdb. Algorithm: sklearn.HistGradientBoostingClassifier (LightGBM stand-in, TQ-022). fraud_score used: no.
Split by process_date: train 2869946 rows (2871 fraud), test from 2025-05-30: 1555062 rows (1445 fraud). Threshold chosen on the training split by cost (missed fraud x10, unnecessary verification x1).

## Gradient boosting (threshold 1.000)

| Split | n | Positives | Recall | Precision | Missed fraud | Unnecessary verifications | ROC AUC | PR AUC | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 2869946 | 2871 | 0.000 | not defined | 2871 | 0 | 0.588 | 0.001 | 28710 |
| test | 1555062 | 1445 | 0.000 | not defined | 1445 | 0 | 0.497 | 0.001 | 14450 |

## Rules baseline (threshold 1.000)

| Split | n | Positives | Recall | Precision | Missed fraud | Unnecessary verifications | ROC AUC | PR AUC | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| train | 2869946 | 2871 | 0.002 | 0.001 | 2865 | 4472 | 0.497 | 0.001 | 33122 |
| test | 1555062 | 1445 | 0.000 | 0.000 | 1445 | 2120 | 0.495 | 0.001 | 16570 |
