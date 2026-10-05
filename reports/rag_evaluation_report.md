# Policy explainer: E5 against BM25 (Hypothesis 5, roadmap Task 4.2)

## Decision rule, fixed before the measurement

Written on 5-Oct, before E5 was run on either split of the policy question bank. It is the rule the roadmap proposed on 30-Sep (`docs/RAG_IMPLEMENTATION_ROADMAP.md`, Task 4.2), taken as written; the team has not ratified it.

E5 is adopted over BM25 only if all three hold on the frozen test split (`data/eval/policy_questions_test.jsonl`, 15 questions in Spanish and 15 in Portuguese):

1. Its Recall@3 beats BM25's by at least 2 questions in Spanish and by at least 2 questions in Portuguese.
2. It gives no more wrong citations than BM25.
3. It passed the bundle check of Task 2.0.

Otherwise BM25 stays. Condition 3 is already known to fail: with scikit-learn in the runtime (TQ-022), E5 takes the bundle to about 609 MB against the 500 MB limit (`docs/SUPABASE_VERCEL.md` section 6.3). So the measurement can support or reject Hypothesis 5, but it cannot change what Vercel serves.

Each retriever gets its gate thresholds from the development split only, and the test split is measured once with them. With 15 questions per language, one question is 6.7 points.

## Result (5-Oct)

Source: `reports/rag_benchmark_e5.md` and `.json` (commit 8e9b9c7; E5 `intfloat/multilingual-e5-small` at revision `614241f622f5`, int8 ONNX, files checked against their SHA-256). BM25's figures there equal the committed `reports/rag_benchmark.json`, latency aside. Offline results on a question bank that is `team-generated, LLM-drafted`.

Test split:

| Measure | BM25 | E5 | Difference |
| --- | --- | --- | --- |
| Recall@3, Spanish | 7 of 11 | 10 of 11 | E5 by 3 questions |
| Recall@3, Portuguese | 9 of 12 | 10 of 12 | E5 by 1 question |
| Recall@3, both | 69.6 % (16 of 23) | 87.0 % (20 of 23) | E5 by 4 questions |
| Wrong citations (of the answers given) | 3 of 11 | 0 of 1 | E5 answered once |
| Wrong abstentions (an answer was expected) | 11 of 18 | 10 of 18 | |
| Correct action | 36.7 % (11 of 30) | 33.3 % (10 of 30) | BM25 by 1 question |
| Latency p50 (ms, in-process) | 0.06 | 6.41 | |

The rule, condition by condition:

1. **Not met.** E5 leads Recall@3 by 3 questions in Spanish and by 1 in Portuguese; the rule asks for 2 in each.
2. **Met.** E5 gave no wrong citation, against 3 for BM25.
3. **Not met.** E5 does not fit the bundle.

**Decision: BM25 stays.** Hypothesis 5 ("multilingual embeddings beat BM25 in recall@3 on ES and PT policy questions") holds in direction in both languages (20 of 23 against 16 of 23), but not by the margin the rule set for Portuguese, and 23 questions cannot separate a 4-question lead from chance.

What the measurement adds:

- **Better retrieval did not become better answers.** E5 finds the right clause more often, yet its correct actions are 10 of 30 against 11 of 30. Its gate (thresholds 0.867 and 0.854, chosen on the development split) let one answer through on the test split: cosine scores sit in a narrow band, so a single cut-off on the top score separates little. The gate, not the retriever, is what limits the explainer.
- **Both abstain too much.** 10 or 11 of the 18 answerable questions get an abstention or a clarification with either retriever.

Limits:

- The run used the dev container on an ARM64 CPU. The int8 model file targets x86 CPUs with AVX-512 VNNI, and the roadmap (Task 2.0) warns that the quantized ranking can differ on other CPUs; the fp32 comparison it asks for was not run.
- 30 questions per split, 15 per language: one question is 6.7 points.
- An LLM drafted the bank after reading the corpus keywords, which favors BM25 (roadmap, Task 1.2).
- The corpus hash in the report (`c2bbf76e977a`) differs from the one in `data/rag_gate.json` (`77776cbc70bd`) only by line endings: the gate was written from a CRLF checkout, and the file has one commit.
