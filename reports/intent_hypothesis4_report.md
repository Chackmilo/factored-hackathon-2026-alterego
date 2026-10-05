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

## Result

Pending: the measurement follows in the next commit.
