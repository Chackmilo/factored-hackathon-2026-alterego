# Jev against the keyword extractor (Hypothesis 4)

Hypothesis 4 of `docs/PLAN.md`: "Jev clasifica la intención mejor que el extractor por palabras clave, con calibración medida por separado en ES y PT."

Measured on 5-Oct, with Kmilo's approval of the spend. Source: `reports/eval_heldout_jev.md` and `.json` (commit 2a7cdfb, 3 repeats), against `reports/eval_heldout.md` (keyword extractor, same suite). Jev is `jev-1.13.0` behind the Understand router, as the API wires it: Jev reads every turn except the trivial ones (a yes, a no, an option number, the lock confirmation), and it sees only the masked message. Each repeat made 300 Jev calls and 33 keyword turns; the three repeats cost 0.035 USD. Offline results on scripted cases, not production gains.

## End to end, on the frozen held-out suite

| Measure | Keyword extractor | Jev behind the router |
| --- | --- | --- |
| Safe automated resolution | 98.1 % (105 of 107) | 98.1 % (105 of 107) |
| Unsafe outcomes | 8.0 % (20 of 250) | 10.4 % (26 of 250) |
| Escalation recall | 79.6 % (78 of 98) | 73.5 % (72 of 98) |
| Escalation precision | 100.0 % (78 of 78) | 100.0 % (72 of 72) |
| Missed / unnecessary transfers | 20 / 0 | 26 / 0 |
| Exact outcome | 88.4 % (221 of 250) | 85.2 % (213 of 250) |
| Latency p50 (ms, same machine; the keyword figure is a rerun that is not committed) | 24.8 | 447.4 |

Paired on the 250 cases (`reports/eval_intervals.md`): no safe resolution gained or lost; 6 cases become unsafe with Jev and none stops being unsafe (exact McNemar p 0.031). The safe resolution rate was the same in the three repeats.

**Hypothesis 4 is not supported on this suite.** Jev does not classify these messages better, and the system with Jev is less safe.

## Why the 6 cases turn unsafe

All 6 need a human (a charge above 500 USD, or several charges in 48 hours) and end in a clarification that no human receives: HO-127, HO-128, HO-131, HO-153, HO-156 and HO-159.

- In HO-127, HO-128 and HO-131 the first message reports a lost or stolen card and an unrecognized charge in one sentence ("Roubaram meu cartão e agora vejo uma compra de ... que não fiz"). Jev splits its answer between `cargo_no_reconocido` and `tarjeta_robada`, so its intent confidence falls under the 0.70 that `POL-CLARIFY` asks for (0.42, 0.68 and 0.64), and the policy asks a question instead of escalating.
- In HO-153, HO-156 and HO-159 the first message is read with confidence 1.00; the difference comes in a later turn of the conversation.

This is the open point of the PLAN row "Lectura de las señales de Jev" (TQ-024): a message with two true intents gets a low confidence on each.

## Intent on the first message, by language

Label: derived from the design label of each case (out of scope when the expected reason is `OUT_OF_SCOPE_INTENT`, a dispute otherwise). 225 first messages were read by Jev and returned signals (12 API attack cases never reach the router, and 13 injected-failure cases end before the signals are returned).

| Language | First messages | Jev right | Keyword right | Out-of-scope found (Jev / keyword) |
| --- | --- | --- | --- | --- |
| Spanish | 134 | 134 | 134 | 6 of 6 / 6 of 6 |
| Portuguese | 91 | 91 | 91 | 2 of 2 / 2 of 2 |

Both engines separate a dispute from an out-of-scope request in every first message, so the suite cannot tell them apart on this label: its messages come from a few templates. The two differ in 7 finer readings: Jev says `tarjeta_robada` where the keywords say `cargo_no_reconocido` (6 messages), and `fuera_de_alcance` where they say `consulta_general` (1, a forgotten card PIN in Portuguese, HO-124, which Jev then routes to the expected abstention).

Calibration of Jev's intent confidence:

| Confidence | Spanish: messages, right | Portuguese: messages, right |
| --- | --- | --- |
| Under 0.70 | 2, 2 | 6, 6 |
| 0.70 to 0.90 | 2, 2 | 1, 1 |
| 0.90 and above | 130, 130 | 84, 84 |

Jev is under-confident, not wrong: the 8 messages under 0.70 are all read correctly, and all 8 are the lost-or-stolen-card sentences above. Six of the eight are Portuguese.

## Development split

On the 19 development cases Jev gave 8 of 9 safe resolutions and 1 of 19 unsafe in the committed run (keywords: 9 of 9 and 0 of 19), and its safe resolution rate moved between 7 and 8 of 9 across three repeats: Jev's answers are not identical from run to run.

## Limits

- 250 scripted conversations from a few templates; 8 out-of-scope first messages. A suite with free-form messages could rank the engines differently.
- All Portuguese is team-generated. Jev's documentation names English as its main language.
- No threshold was tuned. The 0.70 confidence floor is the spec's.
- Production has no Jev key, so it runs the keyword extractor.
