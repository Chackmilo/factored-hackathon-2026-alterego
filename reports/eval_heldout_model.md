# Evaluation report: heldout_cases.jsonl

Cases: 250 (adversarial_or_security: 25, ambiguous: 30, high_fraud_anomaly: 20, high_value_or_multi_charge: 35, incorrect_or_missing_data: 15, multilingual_ambiguity: 10, normal_150_500: 35, normal_le_150: 35, out_of_window_or_unsupported: 25, tool_or_db_failure: 20). Provenance: derived, team-generated. Repeats: 3. Systems: proposed. Versions: commit 53e1545; extractor keyword-v1; policy v2.3; risk model fraud_risk_ieee.joblib (threshold 0.06692), no LLM. Offline results on scripted cases, not production gains.

| Metric | proposed |
| --- | --- |
| Safe automated resolution (eligible cases resolved correctly without a human) | 94.4 % (101 of 107) |
| Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks) | 43.9 % (101 of 230) |
| Attempted automation share | 46.0 % (115 of 250) |
| Containment (ended without transfer) | 62.8 % (157 of 250) |
| Escalation precision | 95.7 % (89 of 93) |
| Escalation recall | 90.8 % (89 of 98) |
| Missed transfers | 9 |
| Unnecessary transfers | 4 |
| Unsafe outcomes | 3.6 % (9 of 250) |
| Unsafe reasons | unauthorized_action:case_opened: 9 |
| Exact outcome accuracy | 90.8 % (227 of 250) |
| Reply language accuracy | 99.2 % (236 of 238) |
| Latency p50 / p95 (ms, in-process, no network) | 27.1 / 313.1 |
| Crashes | 0 |

## Slice by language (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| es | proposed | 150 | 93.4 % (57 of 61) | 2.7 % (4 of 150) | 92.0 % (138 of 150) |
| pt | proposed | 100 | 95.7 % (44 of 46) | 5.0 % (5 of 100) | 89.0 % (89 of 100) |

## Slice by segment (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Basic | proposed | 64 | 96.0 % (24 of 25) | 3.1 % (2 of 64) | 92.2 % (59 of 64) |
| Plus | proposed | 60 | 92.3 % (24 of 26) | 5.0 % (3 of 60) | 86.7 % (52 of 60) |
| Premium | proposed | 64 | 93.5 % (29 of 31) | 4.7 % (3 of 64) | 89.1 % (57 of 64) |
| Student | proposed | 62 | 96.0 % (24 of 25) | 1.6 % (1 of 62) | 95.2 % (59 of 62) |

## Slice by country (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Argentina | proposed | 83 | 94.4 % (34 of 36) | 4.8 % (4 of 83) | 90.4 % (75 of 83) |
| Colombia | proposed | 84 | 94.4 % (34 of 36) | 6.0 % (5 of 84) | 89.3 % (75 of 84) |
| México | proposed | 83 | 94.3 % (33 of 35) | 0.0 % (0 of 83) | 92.8 % (77 of 83) |

## Run-to-run variability

- proposed: safe automated resolution rate min 0.944, max 0.944 over 3 repeats; latency p50 min 27.1 ms, max 27.7 ms

Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. Cost per successful automated resolution: not defined when there are no successes.
