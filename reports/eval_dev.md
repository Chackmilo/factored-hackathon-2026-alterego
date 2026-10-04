# Evaluation report: dev_cases.jsonl

Cases: 19 (adversarial_or_security: 1, ambiguous: 3, high_value_or_multi_charge: 4, incorrect_or_missing_data: 2, normal_150_500: 2, normal_le_150: 4, out_of_window_or_unsupported: 3). Provenance: team-generated. Repeats: 3. Systems: baseline_starter, proposed. Versions: commit 9efb497; extractor keyword-v1; policy v2.3; no ML model, no LLM. Offline results on scripted cases, not production gains.

| Metric | baseline_starter | proposed |
| --- | --- | --- |
| Safe automated resolution (eligible cases resolved correctly without a human) | 0.0 % (0 of 9) | 100.0 % (9 of 9) |
| Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks) | 0.0 % (0 of 18) | 50.0 % (9 of 18) |
| Attempted automation share | 84.2 % (16 of 19) | 47.4 % (9 of 19) |
| Containment (ended without transfer) | 84.2 % (16 of 19) | 73.7 % (14 of 19) |
| Escalation precision | 33.3 % (1 of 3) | 100.0 % (5 of 5) |
| Escalation recall | 20.0 % (1 of 5) | 100.0 % (5 of 5) |
| Missed transfers | 4 | 0 |
| Unnecessary transfers | 2 | 0 |
| Unsafe outcomes | 57.9 % (11 of 19) | 0.0 % (0 of 19) |
| Unsafe reasons | materially_incorrect_outcome: 8, unverified_action: 3 | none |
| Exact outcome accuracy | 42.1 % (8 of 19) | 100.0 % (19 of 19) |
| Reply language accuracy | 54.5 % (6 of 11) | 100.0 % (11 of 11) |
| Latency p50 / p95 (ms, in-process, no network) | 0.1 / 0.1 | 166.3 / 386.0 |
| Crashes | 0 | 0 |

## Slice by language (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| es | baseline_starter | 14 | 0.0 % (0 of 6) | 57.1 % (8 of 14) | 42.9 % (6 of 14) |
| pt | baseline_starter | 5 | 0.0 % (0 of 3) | 60.0 % (3 of 5) | 40.0 % (2 of 5) |
| es | proposed | 14 | 100.0 % (6 of 6) | 0.0 % (0 of 14) | 100.0 % (14 of 14) |
| pt | proposed | 5 | 100.0 % (3 of 3) | 0.0 % (0 of 5) | 100.0 % (5 of 5) |

## Slice by segment (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Basic | baseline_starter | 7 | 0.0 % (0 of 2) | 71.4 % (5 of 7) | 14.3 % (1 of 7) |
| Plus | baseline_starter | 10 | 0.0 % (0 of 6) | 40.0 % (4 of 10) | 60.0 % (6 of 10) |
| Premium | baseline_starter | 2 | 0.0 % (0 of 1) | 100.0 % (2 of 2) | 50.0 % (1 of 2) |
| Basic | proposed | 7 | 100.0 % (2 of 2) | 0.0 % (0 of 7) | 100.0 % (7 of 7) |
| Plus | proposed | 10 | 100.0 % (6 of 6) | 0.0 % (0 of 10) | 100.0 % (10 of 10) |
| Premium | proposed | 2 | 100.0 % (1 of 1) | 0.0 % (0 of 2) | 100.0 % (2 of 2) |

## Slice by country (small samples; read the counts, not the rates)

| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |
| --- | --- | --- | --- | --- | --- |
| Argentina | baseline_starter | 6 | 0.0 % (0 of 3) | 50.0 % (3 of 6) | 33.3 % (2 of 6) |
| Colombia | baseline_starter | 9 | 0.0 % (0 of 5) | 44.4 % (4 of 9) | 55.6 % (5 of 9) |
| México | baseline_starter | 4 | 0.0 % (0 of 1) | 100.0 % (4 of 4) | 25.0 % (1 of 4) |
| Argentina | proposed | 6 | 100.0 % (3 of 3) | 0.0 % (0 of 6) | 100.0 % (6 of 6) |
| Colombia | proposed | 9 | 100.0 % (5 of 5) | 0.0 % (0 of 9) | 100.0 % (9 of 9) |
| México | proposed | 4 | 100.0 % (1 of 1) | 0.0 % (0 of 4) | 100.0 % (4 of 4) |

## Run-to-run variability

- baseline_starter: safe automated resolution rate min 0.000, max 0.000 over 3 repeats; latency p50 min 0.1 ms, max 0.1 ms
- proposed: safe automated resolution rate min 1.000, max 1.000 over 3 repeats; latency p50 min 154.1 ms, max 166.5 ms

Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. Cost per successful automated resolution: not defined when there are no successes.
