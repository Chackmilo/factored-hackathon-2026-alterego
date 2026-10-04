# Evaluation report: heldout_cases.jsonl

Cases: 250 (adversarial_or_security: 25, ambiguous: 30, high_fraud_anomaly: 20, high_value_or_multi_charge: 35, incorrect_or_missing_data: 15, multilingual_ambiguity: 10, normal_150_500: 35, normal_le_150: 35, out_of_window_or_unsupported: 25, tool_or_db_failure: 20). Provenance: derived, team-generated. Repeats: 3. Systems: baseline_starter, proposed. Versions: commit 9efb497; extractor keyword-v1; policy v2.3; no ML model, no LLM. Offline results on scripted cases, not production gains.

| Metric | baseline_starter | proposed |
| --- | --- | --- |
| Safe automated resolution (eligible cases resolved correctly without a human) | 3.7 % (4 of 107) | 98.1 % (105 of 107) |
| Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks) | 1.7 % (4 of 230) | 45.7 % (105 of 230) |
| Attempted automation share | 39.2 % (98 of 250) | 52.4 % (131 of 250) |
| Containment (ended without transfer) | 44.0 % (110 of 250) | 68.8 % (172 of 250) |
| Escalation precision | 48.6 % (68 of 140) | 100.0 % (78 of 78) |
| Escalation recall | 69.4 % (68 of 98) | 79.6 % (78 of 98) |
| Missed transfers | 30 | 20 |
| Unnecessary transfers | 72 | 0 |
| Unsafe outcomes | 48.8 % (122 of 250) | 8.0 % (20 of 250) |
| Unsafe reasons | materially_incorrect_outcome: 35, unauthorized_access: 12, unverified_action: 75 | unauthorized_action:case_opened: 20 |
| Exact outcome accuracy | 52.4 % (131 of 250) | 88.4 % (221 of 250) |
| Reply language accuracy | 59.7 % (142 of 238) | 99.2 % (236 of 238) |
| Latency p50 / p95 (ms, in-process, no network) | 0.1 / 0.2 | 161.6 / 662.1 |
| Crashes | 0 | 0 |

## Slice by language (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| es | baseline_starter | 150 | 6.6 % (4 of 61) | 48.7 % (73 of 150) | 50.7 % (76 of 150) |
| pt | baseline_starter | 100 | 0.0 % (0 of 46) | 49.0 % (49 of 100) | 55.0 % (55 of 100) |
| es | proposed | 150 | 96.7 % (59 of 61) | 8.0 % (12 of 150) | 88.0 % (132 of 150) |
| pt | proposed | 100 | 100.0 % (46 of 46) | 8.0 % (8 of 100) | 89.0 % (89 of 100) |

## Slice by segment (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Basic | baseline_starter | 64 | 4.0 % (1 of 25) | 54.7 % (35 of 64) | 51.6 % (33 of 64) |
| Plus | baseline_starter | 60 | 3.8 % (1 of 26) | 46.7 % (28 of 60) | 55.0 % (33 of 60) |
| Premium | baseline_starter | 64 | 0.0 % (0 of 31) | 40.6 % (26 of 64) | 56.2 % (36 of 64) |
| Student | baseline_starter | 62 | 8.0 % (2 of 25) | 53.2 % (33 of 62) | 46.8 % (29 of 62) |
| Basic | proposed | 64 | 100.0 % (25 of 25) | 6.2 % (4 of 64) | 90.6 % (58 of 64) |
| Plus | proposed | 60 | 100.0 % (26 of 26) | 10.0 % (6 of 60) | 86.7 % (52 of 60) |
| Premium | proposed | 64 | 96.8 % (30 of 31) | 9.4 % (6 of 64) | 85.9 % (55 of 64) |
| Student | proposed | 62 | 96.0 % (24 of 25) | 6.5 % (4 of 62) | 90.3 % (56 of 62) |

## Slice by country (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Argentina | baseline_starter | 83 | 8.3 % (3 of 36) | 44.6 % (37 of 83) | 59.0 % (49 of 83) |
| Colombia | baseline_starter | 84 | 2.8 % (1 of 36) | 52.4 % (44 of 84) | 45.2 % (38 of 84) |
| México | baseline_starter | 83 | 0.0 % (0 of 35) | 49.4 % (41 of 83) | 53.0 % (44 of 83) |
| Argentina | proposed | 83 | 97.2 % (35 of 36) | 8.4 % (7 of 83) | 88.0 % (73 of 83) |
| Colombia | proposed | 84 | 97.2 % (35 of 36) | 8.3 % (7 of 84) | 89.3 % (75 of 84) |
| México | proposed | 83 | 100.0 % (35 of 35) | 7.2 % (6 of 83) | 88.0 % (73 of 83) |

## Run-to-run variability

- baseline_starter: safe automated resolution rate min 0.037, max 0.037 over 3 repeats; latency p50 min 0.1 ms, max 0.1 ms
- proposed: safe automated resolution rate min 0.981, max 0.981 over 3 repeats; latency p50 min 161.6 ms, max 167.3 ms

Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. Cost per successful automated resolution: not defined when there are no successes.
