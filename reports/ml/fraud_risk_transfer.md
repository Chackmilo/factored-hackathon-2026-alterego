# Fraud risk transfer report (2026-09-30T00:52:00, commit f7c0eb5)

Contract v1.1, 19 deployable features, fraud_score used: no. sklearn.HistGradientBoostingClassifier on per-source percentile ranks (LightGBM stand-in, TQ-022).

## Competition time split

| Split | n | Positives | ROC AUC | PR AUC | Recall at cost threshold | Precision |
| --- | --- | --- | --- | --- | --- | --- |
| train | 487,837 | 17,150 | 0.859 | 0.338 | 0.540 | 0.211 |
| test | 102,703 | 3,513 | 0.817 | 0.165 | 0.404 | 0.176 |

## Ablations (holdout)

| Ablation | Dropped | ROC AUC | PR AUC |
| --- | --- | --- | --- |
| without_card_aggregates | days_since_prev_tx_card, tx_count_card_1d, tx_count_card_7d, tx_count_card_30d, tx_sum_card_7d, amount_mean_card_hist, amount_std_card_hist, amount_zscore_card, ratio_to_historical_avg | 0.785 | 0.145 |
| without_discrete_block | amount_has_cents, day_of_week, card_kind_credit, card_kind_debit, address_distance_bucket, consistency_matches | 0.755 | 0.090 |

## Bank calibration

75,366 charges on Web, App in the 60 days to 2026-06-17; threshold = percentile 98 of their scores = 0.0669; share above: 0.020; agreement with is_fraud (73 flags): ROC AUC 0.507.

## Caveats

- The competition holds card-not-present rows only: the score is served on Web and App charges, the rules baseline covers the rest.
- The bank label carries no learnable signal (discussion doc sections 5 and 6); its agreement is reported, never optimized.
