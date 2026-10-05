# Policy explainer: E5 against BM25 (Hypothesis 5, roadmap Task 4.2)

## Decision rule, fixed before the measurement

Written on 5-Oct, before E5 was run on either split of the policy question bank. It is the rule the roadmap proposed on 30-Sep (`docs/RAG_IMPLEMENTATION_ROADMAP.md`, Task 4.2), taken as written; the team has not ratified it.

E5 is adopted over BM25 only if all three hold on the frozen test split (`data/eval/policy_questions_test.jsonl`, 15 questions in Spanish and 15 in Portuguese):

1. Its Recall@3 beats BM25's by at least 2 questions in Spanish and by at least 2 questions in Portuguese.
2. It gives no more wrong citations than BM25.
3. It passed the bundle check of Task 2.0.

Otherwise BM25 stays. Condition 3 is already known to fail: with scikit-learn in the runtime (TQ-022), E5 takes the bundle to about 609 MB against the 500 MB limit (`docs/SUPABASE_VERCEL.md` section 6.3). So the measurement can support or reject Hypothesis 5, but it cannot change what Vercel serves.

Each retriever gets its gate thresholds from the development split only, and the test split is measured once with them. With 15 questions per language, one question is 6.7 points.

## Result

Pending: the measurement follows in the next commit.
