# Evaluation report: heldout_cases.jsonl

Cases: 250 (adversarial_or_security: 25, ambiguous: 30, high_fraud_anomaly: 20, high_value_or_multi_charge: 35, incorrect_or_missing_data: 15, multilingual_ambiguity: 10, normal_150_500: 35, normal_le_150: 35, out_of_window_or_unsupported: 25, tool_or_db_failure: 20). Provenance: derived, team-generated. Repeats: 3. Systems: proposed. Versions: commit 8fef59e; extractor keyword-v1; policy v2.3; no ML model, no LLM; policy explainer bm25 (rag_gate.json). Offline results on scripted cases, not production gains.

| Metric | proposed |
| --- | --- |
| Safe automated resolution (eligible cases resolved correctly without a human) | 98.1 % (105 of 107) |
| Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks) | 45.7 % (105 of 230) |
| Attempted automation share | 52.4 % (131 of 250) |
| Containment (ended without transfer) | 68.8 % (172 of 250) |
| Escalation precision | 100.0 % (78 of 78) |
| Escalation recall | 79.6 % (78 of 98) |
| Missed transfers | 20 |
| Unnecessary transfers | 0 |
| Unsafe outcomes | 8.0 % (20 of 250) |
| Unsafe reasons | unauthorized_action:case_opened: 20 |
| Exact outcome accuracy | 88.4 % (221 of 250) |
| Reply language accuracy | 99.2 % (236 of 238) |
| Latency p50 / p95 (ms, in-process, no network) | 23.7 / 80.6 |
| Crashes | 0 |

## Slice by language (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| es | proposed | 150 | 96.7 % (59 of 61) | 8.0 % (12 of 150) | 88.0 % (132 of 150) |
| pt | proposed | 100 | 100.0 % (46 of 46) | 8.0 % (8 of 100) | 89.0 % (89 of 100) |

## Slice by segment (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Basic | proposed | 64 | 100.0 % (25 of 25) | 6.2 % (4 of 64) | 90.6 % (58 of 64) |
| Plus | proposed | 60 | 100.0 % (26 of 26) | 10.0 % (6 of 60) | 86.7 % (52 of 60) |
| Premium | proposed | 64 | 96.8 % (30 of 31) | 9.4 % (6 of 64) | 85.9 % (55 of 64) |
| Student | proposed | 62 | 96.0 % (24 of 25) | 6.5 % (4 of 62) | 90.3 % (56 of 62) |

## Slice by country (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Argentina | proposed | 83 | 97.2 % (35 of 36) | 8.4 % (7 of 83) | 88.0 % (73 of 83) |
| Colombia | proposed | 84 | 97.2 % (35 of 36) | 8.3 % (7 of 84) | 89.3 % (75 of 84) |
| México | proposed | 83 | 100.0 % (35 of 35) | 7.2 % (6 of 83) | 88.0 % (73 of 83) |

## Run-to-run variability

- proposed: safe automated resolution rate min 0.981, max 0.981 over 3 repeats; latency p50 min 23.7 ms, max 24.0 ms

Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. Cost per successful automated resolution: not defined when there are no successes.
