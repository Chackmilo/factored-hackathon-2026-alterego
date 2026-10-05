# Policy explainer benchmark

Development split: `data/eval/policy_questions_dev.jsonl`, 30 questions (team-generated, LLM-drafted). Test split: `data/eval/policy_questions_test.jsonl`, 30 questions (team-generated, LLM-drafted), matches its SHA-256. Corpus SHA-256 `c2bbf76e977a`; commit 8e9b9c7. The thresholds come from the development split only; the test split is measured once with them. Offline results on the questions of the stated provenance; the retrievers are deterministic, so one run. E5: `intfloat/multilingual-e5-small` at revision `614241f622f5`, int8 ONNX, files checked against their SHA-256.

## bm25 (gate: tau_upper 3.862, tau_lower 3.835)

| Metric | Development | Test |
| --- | --- | --- |
| Recall@1 | 56.5 % (13 of 23) | 52.2 % (12 of 23) |
| Recall@3 | 82.6 % (19 of 23) | 69.6 % (16 of 23) |
| Correct action | 56.7 % (17 of 30) | 36.7 % (11 of 30) |
| Out-of-scope questions abstained | 100.0 % (7 of 7) | 85.7 % (6 of 7) |
| Wrong abstention (an answer was expected) | 33.3 % (6 of 18) | 61.1 % (11 of 18) |
| Wrong citation (of the answers given) | 21.4 % (3 of 14) | 27.3 % (3 of 11) |
| MRR | 0.720 (of 23) | 0.638 (of 23) |
| Latency p50 / p95 (ms, in-process) | 0.06 / 0.09 | 0.06 / 0.11 |

Slice by language (small samples; read the counts, not the rates):

| Language | Split | n | Recall@3 | Correct action | Wrong citation |
| --- | --- | --- | --- | --- | --- |
| es | dev | 15 | 75.0 % (9 of 12) | 53.3 % (8 of 15) | 20.0 % (1 of 5) |
| es | test | 15 | 63.6 % (7 of 11) | 40.0 % (6 of 15) | 20.0 % (1 of 5) |
| pt | dev | 15 | 90.9 % (10 of 11) | 60.0 % (9 of 15) | 22.2 % (2 of 9) |
| pt | test | 15 | 75.0 % (9 of 12) | 33.3 % (5 of 15) | 33.3 % (2 of 6) |

## e5 (gate: tau_upper 0.867, tau_lower 0.854)

| Metric | Development | Test |
| --- | --- | --- |
| Recall@1 | 34.8 % (8 of 23) | 56.5 % (13 of 23) |
| Recall@3 | 95.7 % (22 of 23) | 87.0 % (20 of 23) |
| Correct action | 50.0 % (15 of 30) | 33.3 % (10 of 30) |
| Out-of-scope questions abstained | 100.0 % (7 of 7) | 85.7 % (6 of 7) |
| Wrong abstention (an answer was expected) | 44.4 % (8 of 18) | 55.6 % (10 of 18) |
| Wrong citation (of the answers given) | 14.3 % (1 of 7) | 0.0 % (0 of 1) |
| MRR | 0.641 (of 23) | 0.743 (of 23) |
| Latency p50 / p95 (ms, in-process) | 6.20 / 7.30 | 6.41 / 8.96 |

Slice by language (small samples; read the counts, not the rates):

| Language | Split | n | Recall@3 | Correct action | Wrong citation |
| --- | --- | --- | --- | --- | --- |
| es | dev | 15 | 91.7 % (11 of 12) | 53.3 % (8 of 15) | 25.0 % (1 of 4) |
| es | test | 15 | 90.9 % (10 of 11) | 33.3 % (5 of 15) | 0.0 % (0 of 1) |
| pt | dev | 15 | 100.0 % (11 of 11) | 46.7 % (7 of 15) | 0.0 % (0 of 3) |
| pt | test | 15 | 83.3 % (10 of 12) | 33.3 % (5 of 15) | not defined (0 of 0) |
