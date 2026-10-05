# Intent benchmark: keyword extractor, Jev and a mix of both

Development split `data/eval/intent_messages_dev.jsonl` (40 messages); test split `data/eval/intent_messages_test.jsonl` (100 messages, matches its SHA-256). Provenance: team-generated, LLM-drafted. Commit 5a17f65. Jev: jev jev-1.13.0; spend 0.010438 USD. A message is read right when the engine names exactly its set of labels. Offline results on the stated provenance.

## Development split

| Engine | Spanish | Portuguese | All | Jev calls |
| --- | --- | --- | --- | --- |
| keyword | 65.0 % (13 of 20) | 65.0 % (13 of 20) | 65.0 % (26 of 40) | none |
| jev | 95.0 % (19 of 20) | 90.0 % (18 of 20) | 92.5 % (37 of 40) | every message |
| gate | 95.0 % (19 of 20) | 95.0 % (19 of 20) | 95.0 % (38 of 40) | 15 (38 %) |
| gate_union | 95.0 % (19 of 20) | 95.0 % (19 of 20) | 95.0 % (38 of 40) | 15 (38 %) |

Paired, keyword against Jev: 1 messages only the keywords read right, 12 only Jev; exact McNemar p 0.0034. Jev's category of the other request: 100.0 % (12 of 12).

| Label | Engine | Found | Missed | Wrongly named |
| --- | --- | --- | --- | --- |
| disputa | keyword | 15 | 5 | 2 |
| disputa | jev | 19 | 1 | 0 |
| tarjeta | keyword | 6 | 2 | 0 |
| tarjeta | jev | 8 | 0 | 0 |
| reglas | keyword | 4 | 0 | 0 |
| reglas | jev | 4 | 0 | 0 |
| fuera | keyword | 7 | 7 | 0 |
| fuera | jev | 12 | 2 | 0 |

Calibration of Jev's yes or no answers (Brier score; expected calibration error over five bins):

| Answer | Spanish | Portuguese |
| --- | --- | --- |
| dispute | Brier 0.021, ECE 0.077 (n 20) | Brier 0.024, ECE 0.041 (n 20) |
| stolen_card | Brier 0.001, ECE 0.026 (n 20) | Brier 0.001, ECE 0.026 (n 20) |
| other_request | Brier 0.032, ECE 0.120 (n 20) | Brier 0.019, ECE 0.100 (n 20) |

## Test split

| Engine | Spanish | Portuguese | All | Jev calls |
| --- | --- | --- | --- | --- |
| keyword | 44.0 % (22 of 50) | 54.0 % (27 of 50) | 49.0 % (49 of 100) | none |
| jev | 92.0 % (46 of 50) | 92.0 % (46 of 50) | 92.0 % (92 of 100) | every message |
| gate | 80.0 % (40 of 50) | 82.0 % (41 of 50) | 81.0 % (81 of 100) | 58 (58 %) |
| gate_union | 80.0 % (40 of 50) | 80.0 % (40 of 50) | 80.0 % (80 of 100) | 58 (58 %) |

Paired, keyword against Jev: 1 messages only the keywords read right, 44 only Jev; exact McNemar p 0.0000. Jev's category of the other request: 100.0 % (23 of 23).

| Label | Engine | Found | Missed | Wrongly named |
| --- | --- | --- | --- | --- |
| disputa | keyword | 43 | 19 | 2 |
| disputa | jev | 59 | 3 | 0 |
| tarjeta | keyword | 6 | 18 | 1 |
| tarjeta | jev | 23 | 1 | 0 |
| reglas | keyword | 7 | 1 | 0 |
| reglas | jev | 7 | 1 | 0 |
| fuera | keyword | 11 | 15 | 2 |
| fuera | jev | 23 | 3 | 0 |

Calibration of Jev's yes or no answers (Brier score; expected calibration error over five bins):

| Answer | Spanish | Portuguese |
| --- | --- | --- |
| dispute | Brier 0.032, ECE 0.072 (n 50) | Brier 0.033, ECE 0.087 (n 50) |
| stolen_card | Brier 0.003, ECE 0.037 (n 50) | Brier 0.009, ECE 0.046 (n 50) |
| other_request | Brier 0.025, ECE 0.116 (n 50) | Brier 0.022, ECE 0.115 (n 50) |

Mix chosen on the development split: `gate`.
