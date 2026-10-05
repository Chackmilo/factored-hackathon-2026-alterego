# Evaluation report: heldout_cases.jsonl

Cases: 250 (adversarial_or_security: 25, ambiguous: 30, high_fraud_anomaly: 20, high_value_or_multi_charge: 35, incorrect_or_missing_data: 15, multilingual_ambiguity: 10, normal_150_500: 35, normal_le_150: 35, out_of_window_or_unsupported: 25, tool_or_db_failure: 20). Provenance: derived, team-generated. Repeats: 3. Systems: proposed. Versions: commit 2a7cdfb; extractor jev behind the router (keyword-v1 on trivial turns and as fallback); policy v2.3; no ML model, no LLM. Offline results on scripted cases, not production gains.

| Metric | proposed |
| --- | --- |
| Safe automated resolution (eligible cases resolved correctly without a human) | 98.1 % (105 of 107) |
| Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks) | 45.7 % (105 of 230) |
| Attempted automation share | 51.2 % (128 of 250) |
| Containment (ended without transfer) | 71.2 % (178 of 250) |
| Escalation precision | 100.0 % (72 of 72) |
| Escalation recall | 73.5 % (72 of 98) |
| Missed transfers | 26 |
| Unnecessary transfers | 0 |
| Unsafe outcomes | 10.4 % (26 of 250) |
| Unsafe reasons | materially_incorrect_outcome: 6, unauthorized_action:case_opened: 20 |
| Exact outcome accuracy | 85.2 % (213 of 250) |
| Reply language accuracy | 99.2 % (236 of 238) |
| Latency p50 / p95 (ms, in-process, no network) | 447.4 / 1375.1 |
| Crashes | 0 |

## Slice by language (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| es | proposed | 150 | 96.7 % (59 of 61) | 8.7 % (13 of 150) | 86.7 % (130 of 150) |
| pt | proposed | 100 | 100.0 % (46 of 46) | 13.0 % (13 of 100) | 83.0 % (83 of 100) |

## Slice by segment (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Basic | proposed | 64 | 100.0 % (25 of 25) | 9.4 % (6 of 64) | 87.5 % (56 of 64) |
| Plus | proposed | 60 | 100.0 % (26 of 26) | 13.3 % (8 of 60) | 81.7 % (49 of 60) |
| Premium | proposed | 64 | 96.8 % (30 of 31) | 9.4 % (6 of 64) | 84.4 % (54 of 64) |
| Student | proposed | 62 | 96.0 % (24 of 25) | 9.7 % (6 of 62) | 87.1 % (54 of 62) |

## Slice by country (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Argentina | proposed | 83 | 97.2 % (35 of 36) | 9.6 % (8 of 83) | 86.7 % (72 of 83) |
| Colombia | proposed | 84 | 97.2 % (35 of 36) | 14.3 % (12 of 84) | 82.1 % (69 of 84) |
| México | proposed | 83 | 100.0 % (35 of 35) | 7.2 % (6 of 83) | 86.7 % (72 of 83) |

## Run-to-run variability

- proposed: safe automated resolution rate min 0.981, max 0.981 over 3 repeats; latency p50 min 440.0 ms, max 447.4 ms

Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. Cost per successful automated resolution: not defined when there are no successes.
