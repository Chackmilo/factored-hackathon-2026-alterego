# Hypothesis 4, tested: Jev against the keyword extractor on customer messages

Hypothesis 4 of `docs/PLAN.md`: "Jev clasifica la intención mejor que el extractor por palabras clave, con calibración medida por separado en ES y PT."

## Why a new bank

The held-out suite cannot test it: its first messages come from a few templates, and both engines read all 225 of them right (`reports/jev_evaluation_report.md`). This test uses a bank of customer messages written to vary the wording: paraphrases without the usual words, regional speech, typos, several topics in one message, requests this channel does not handle, questions about the rules and greetings.

- `data/eval/intent_messages_dev.jsonl`: 40 messages (20 Spanish, 20 Portuguese), for choosing the mixed rule below.
- `data/eval/intent_messages_test.jsonl`: 100 messages (50 Spanish, 50 Portuguese), frozen with `intent_messages_test.sha256`. The Portuguese messages say the same things as the Spanish ones, so the two languages are compared on the same content.
- Provenance: `team-generated, LLM-drafted`. Claude Code wrote the messages and their labels on 5-Oct from the topic definitions of `src/understand/topics.py`; no person has reviewed the labels. The same author had worked on the keyword extractor that day. The messages were written as a customer would write them, without consulting the keyword lists, which favors neither engine by design but cannot be shown to.

Each message is labeled with the topics it carries, any of: a charge dispute, the card lost or stolen, a question about the rules, a request this channel does not handle (with its category). A message is read right when the engine names exactly that set.

## Decision rules, fixed before any engine read the test split

Written on 5-Oct and committed with the bank, before the keyword extractor or Jev was run on the test split.

**Hypothesis 4 is supported** only if both hold on the 100 test messages:

1. Jev reads more messages right than the keyword extractor, and the exact McNemar test on the paired messages gives p under 0.05.
2. Jev is ahead in Spanish and in Portuguese, each counted on its 50 messages.

Calibration is reported apart for Spanish and Portuguese, for each of Jev's three yes or no answers (disputes a charge, card lost or stolen, asks for something else): the Brier score and the expected calibration error over five bins. It is described, not passed or failed.

**The mix of keywords and Jev.** Two mixed rules are compared on the development split, and the better one (most messages right; on a tie, the one with fewer Jev calls) is then measured once on the test split:

- *Gate:* Jev is called only when the keyword reading is not sure of itself, which means no topic was found, or the dispute was guessed from a charge word or an amount without a dispute phrase. When Jev is called, Jev's reading stands.
- *Gate and union:* the same gate, and when Jev is called a topic counts if either engine names it.

For the mix the report gives the messages read right and the share of messages that needed a Jev call.

## Result (5-Oct)

Source: `reports/intent_benchmark.md` and `.json` (commit 5a17f65; Jev `jev-1.13.0`, 140 real calls, 0.010 USD). One run: the test split was read once.

**Hypothesis 4 is supported on this bank.** Both rules hold.

| Test split, messages read right | Spanish | Portuguese | All |
| --- | --- | --- | --- |
| Keyword extractor | 44.0 % (22 of 50) | 54.0 % (27 of 50) | 49.0 % (49 of 100) |
| Jev | 92.0 % (46 of 50) | 92.0 % (46 of 50) | 92.0 % (92 of 100) |
| Mix chosen on development (`gate`) | 80.0 % (40 of 50) | 82.0 % (41 of 50) | 81.0 % (81 of 100) |

1. **Met.** Jev reads 92 of 100 right against 49. On the paired messages, 44 are read right only by Jev and 1 only by the keywords: exact McNemar p under 0.0001.
2. **Met.** Jev is ahead in Spanish (46 against 22) and in Portuguese (46 against 27).

By label on the test split (found, missed, wrongly named):

| Label | Messages that carry it | Keyword extractor | Jev |
| --- | --- | --- | --- |
| Charge dispute | 62 | 43, 19, 2 | 59, 3, 0 |
| Card lost or stolen | 24 | 6, 18, 1 | 23, 1, 0 |
| Question about the rules | 8 | 7, 1, 0 | 7, 1, 0 |
| Request of another channel | 26 | 11, 15, 2 | 23, 3, 0 |

The keyword extractor misses what is not said in its words: 18 of the 24 lost or stolen cards ("se me perdió la billetera con todo y tarjeta", "levaram minha carteira"), 19 of the 62 disputes and 15 of the 26 other requests. Jev named the category of the other request right in all 23 it found. The question about the rules is the same for both, since Jev is not asked it.

### Calibration, by language

| Jev's answer | Spanish (50) | Portuguese (50) |
| --- | --- | --- |
| Disputes a charge | Brier 0.032, ECE 0.072 | Brier 0.033, ECE 0.087 |
| Card lost or stolen | Brier 0.003, ECE 0.037 | Brier 0.009, ECE 0.046 |
| Asks for something else | Brier 0.025, ECE 0.116 | Brier 0.022, ECE 0.115 |

The two languages are close on every answer. The card answer is the best calibrated; the "asks for something else" answer is the least, at about 0.12 in both languages.

**Jev's misses are doubts, not confident errors.** In all 8 test messages Jev reads wrong, the answer it gets wrong sits between 0.40 and 0.48, just under the 0.50 that makes a topic: "Perdí la tarjeta en el estadio y ya me gastaron 150 dólares" (dispute 0.48), "Se me bloqueó el PIN por meter mal la clave tres veces" (other request 0.43), "Sumiu meu cartão, o que eu faço?" (card 0.40). The policy already treats that band as doubt and asks the customer.

### The mix of keywords and Jev

The mix that calls Jev only when the keywords are not sure of themselves reads 81 of 100 right with Jev on 58 of the 100 messages: it saves 42 % of the calls and loses 11 messages against Jev alone. On the development split it had looked as good as Jev (38 of 40 against 37).

The reason is in the 42 messages where the keywords were sure and Jev was not called: the keywords read 28 of them right, and Jev would have read 39. A keyword reading that found a dispute phrase is sure of the dispute, and blind to what else the message says: of its 14 errors, 6 miss a dispute, 4 miss the card and the rest miss or misname another request.

So a mix by "how sure the keywords are" is not the structure to use. The structure the results support is a split by kind of information, which the router already has:

- **Jev reads the meaning** (which topics the message carries), one yes or no per statement.
- **The keyword extractor reads the exact data**: amounts, dates, the yes or no to the lock question and the option number, always from the raw text.
- **The keyword extractor takes the turns that need no reading** (a bare yes, an option number, the lock answer) and every turn when Jev has no key, no budget or fails.
- **Jev's doubt band asks the customer** instead of deciding.

Cost is not the constraint that would justify the gate: 140 calls cost one cent.

### The structured mix against Jev on its own

Computed after the run, from the answers stored in `reports/intent_benchmark.json`; no new call, no threshold chosen on these messages. The row called "Jev" above is already the structured mix: Jev's three answers plus the keyword signal for a question about the rules, which Jev is not asked. Jev on its own is the three answers alone.

| Test split | Spanish | Portuguese | All |
| --- | --- | --- | --- |
| Keyword extractor alone | 22 of 50 | 27 of 50 | 49 of 100 |
| Jev alone (its three answers) | 43 of 50 | 42 of 50 | 85 of 100 |
| Structured mix (Jev for the topics, keywords for the rules question) | 46 of 50 | 46 of 50 | 92 of 100 |

The mix reads 7 messages right that Jev alone misses and loses none (exact McNemar p 0.016). All 7 are questions about the rules: Jev alone sees no topic in 6 of the 8 and reads the other 2 as disputes ("Si disputo un cargo, ¿cuánto se demoran en responderme?"). On the development split the mix is 37 of 40 against 34.

With the doubt band the policy already has (an answer between 0.40 and 0.60 asks the customer instead of deciding):

| Test split, structured mix | Messages |
| --- | --- |
| Decided, and right | 88 |
| Asked the customer | 12 (4 of them it had read right) |
| Decided, and wrong | 0 |

Every one of the 8 wrong readings falls in the band, so none becomes a wrong decision; the price is 4 questions the customer did not need.

### Limits

- One author wrote the messages and the labels, the same day and without a second reader. Labels on the edge are debatable: "Cancelei a assinatura faz meses e continuam debitando todo mês" is labeled a dispute, and "No reconozco la cuota que me están cobrando del préstamo" is labeled a loan request by the team's rule that a loan installment is not a card charge.
- The messages were written to vary the wording, which is where a keyword list is weakest. On the template messages of the held-out suite both engines read 225 of 225 right. Real customer messages sit somewhere between the two banks, and the bank has none.
- 100 test messages, 50 per language: the intervals are wide (Jev 92 %, Wilson 95 % interval 85.0 to 95.9 %; keywords 49 %, 39.4 to 58.7 %).
- This measures the reading of one message, not the outcome of a conversation. End to end on the held-out suite Jev and the keywords are equally safe (`reports/jev_evaluation_report.md`).
- Production has no Jev key: it runs the keyword extractor. Turning Jev on there is a decision of its own (a key in Vercel and the daily cap).
