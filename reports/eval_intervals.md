# Evaluation intervals and paired tests

Suite: `data/eval/heldout_cases.jsonl`. Wilson 95 % intervals for each rate; exact McNemar test on the cases where the two systems disagree. Written by `src/eval/intervals.py` from the committed report JSONs. Offline results on scripted cases, not production gains.

The intervals cover sampling error only. The cases come from a few templates, so they are less independent than the formulas assume: read each interval as a lower bound on the uncertainty.

## Blind run (30-Sep): starter pipeline against the proposed stack, rules only

- A: `baseline_starter` in `reports/eval_heldout_blind.json` (commit 011e931; extractor keyword-v1; policy v2.3; no ML model, no LLM; outcomes from commit 011e931 (PR #12, the first blind run of 30-Sep), re-scored with the TQ-034 and TQ-035 judge and metrics of commit 3dc2fdf)
- B: `proposed` in `reports/eval_heldout_blind.json` (commit 011e931; extractor keyword-v1; policy v2.3; no ML model, no LLM; outcomes from commit 011e931 (PR #12, the first blind run of 30-Sep), re-scored with the TQ-034 and TQ-035 judge and metrics of commit 3dc2fdf)

| Metric | A | B | Only A | Only B | Exact p |
| --- | --- | --- | --- | --- | --- |
| Safe automated resolution (eligible cases) | 3.7 % (4 of 107), 95 % interval 1.5 to 9.2 % | 63.6 % (68 of 107), 95 % interval 54.1 to 72.1 % | 1 | 65 | under 0.001 |
| Unsafe outcomes (all cases) | 48.8 % (122 of 250), 95 % interval 42.7 to 55.0 % | 15.6 % (39 of 250), 95 % interval 11.6 to 20.6 % | 102 | 19 | under 0.001 |

## After the error analysis: starter pipeline against the proposed stack, rules only

- A: `baseline_starter` in `reports/eval_heldout.json` (commit 9efb497; extractor keyword-v1; policy v2.3; no ML model, no LLM)
- B: `proposed` in `reports/eval_heldout.json` (commit 9efb497; extractor keyword-v1; policy v2.3; no ML model, no LLM)

| Metric | A | B | Only A | Only B | Exact p |
| --- | --- | --- | --- | --- | --- |
| Safe automated resolution (eligible cases) | 3.7 % (4 of 107), 95 % interval 1.5 to 9.2 % | 98.1 % (105 of 107), 95 % interval 93.4 to 99.5 % | 1 | 102 | under 0.001 |
| Unsafe outcomes (all cases) | 48.8 % (122 of 250), 95 % interval 42.7 to 55.0 % | 8.0 % (20 of 250), 95 % interval 5.2 to 12.0 % | 113 | 11 | under 0.001 |

## Proposed stack: rules only against rules plus the transferred risk model

- A: `proposed` in `reports/eval_heldout.json` (commit 9efb497; extractor keyword-v1; policy v2.3; no ML model, no LLM)
- B: `proposed` in `reports/eval_heldout_model.json` (commit 8489a97; extractor keyword-v1; policy v2.3; risk model fraud_risk_ieee.joblib (threshold 0.06365), no LLM)

| Metric | A | B | Only A | Only B | Exact p |
| --- | --- | --- | --- | --- | --- |
| Safe automated resolution (eligible cases) | 98.1 % (105 of 107), 95 % interval 93.4 to 99.5 % | 94.4 % (101 of 107), 95 % interval 88.3 to 97.4 % | 4 | 0 | 0.125 |
| Unsafe outcomes (all cases) | 8.0 % (20 of 250), 95 % interval 5.2 to 12.0 % | 3.6 % (9 of 250), 95 % interval 1.9 to 6.7 % | 11 | 0 | under 0.001 |

"Only A" counts the cases where A has the outcome and B does not (a safe resolution in the first row, an unsafe outcome in the second); "Only B" is the reverse.
