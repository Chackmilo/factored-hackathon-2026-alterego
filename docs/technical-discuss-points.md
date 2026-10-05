# Technical discussion points

Working notes for decisions that need the team. Each point states the evidence measured in this repo, the options, a recommendation and what changes in code or spec. Numbers come from `data/lakehouse.duckdb` rebuilt on 2026-09-27 (June 2026 transactions of the 25,000-customer sample, 11,703 rows) unless a wider probe is named. Re-check against the full load before quoting a number as final.

## 1. Null `amount_usd`: is it a data defect, and can it be corrected? (spec question P2)

### 1.1 What the data shows

Two different situations share the same null, and only one of them is a gap.

| Currency | Rows | `amount_usd` null | Share | Reading |
| --- | --- | --- | --- | --- |
| USD | 6,449 | 6,449 | 100 % | By design: the amount is already in USD, nothing to convert |
| COP | 3,214 | 185 | 5.76 % | Real gap |
| ARS | 2,040 | 106 | 5.20 % | Real gap |

The 291 real gaps are all fillable:

- `daily_exchange_rates` covers every day from 2023-06-17 to 2026-06-17 (1,097 dates, 12 currency pairs, four `source` values). A `COP->USD` or `ARS->USD` rate exists for the `process_date` of all 291 rows.
- Where the native `amount_usd` exists, it equals `amount * exchange_rate` (the mid rate of the process day) within a symmetric noise band: ratio native over computed runs from 0.980 to 1.020 with median 1.000, average distance under 1 %, maximum 2.01 %. `buy_rate` and `sell_rate` fit worse, and the rate of the UTC calendar date fits no better than the process date. The noise is synthetic, not a spread.
- The direction is multiply, never divide: `COP->USD` on 2026-06-17 is 0.000248 and `USD->COP` is 4,054.70.
- The fill changes policy outcomes. Of the 291 rows, 138 convert to more than $500 (`POL-ESC-500`) and 45 to $150 or less (possible `POL-AUT-150` candidates). Of the 291, 226 are disputable in-window charges (145 COP, 81 ARS), 2.5 % of the 8,967 the policy funnel counts.

### 1.2 What the code does today

`src/data/ingestion.py` already fills the gap, but silently and in the gold layer only: `gold_transactions.amount_usd_normalized` takes `amount` for USD, the native `amount_usd` when present, and otherwise `amount * COALESCE(daily rate, latest rate, 1.0)`. In the June sample this yields 0 nulls and the `1.0` fallback never fires. Three weaknesses remain:

1. No column says which rows were filled, so a reviewer cannot tell a dataset value from a computed one.
2. The original value is kept only under its raw name; a consumer that reads `amount_usd` from silver still sees the null, and the app's serving copy (`bank`) was planned from gold.
3. The `1.0` fallback would treat pesos as dollars if a rate were ever missing (`AGENTS.md` section 7 already asks to fail the load instead).

### 1.3 Business reading

Agreed with the team's position: this is not a business problem once a cleaning step exists. USD rows need no conversion, the 291 non-USD gaps have a rate for their day, and the dataset's own conversions use that same rate. What the business needs is that the fix is visible (a descriptive flag), reversible (the original values kept) and safe (no silent default when a rate is missing).

### 1.4 Proposed cleaning design (data front, `src/data/ingestion.py`, silver layer)

Move the fill from gold to silver so every downstream table, including the serving copy, reads one filled column with its provenance.

| Column | Meaning |
| --- | --- |
| `amount_usd_legacy` | The raw dataset value, untouched and nullable. Rollback path: it is the previous real value |
| `amount_usd` | Filled value: `amount` when `currency = 'USD'`; the native value when present; otherwise `ROUND(amount * exchange_rate, 2)` using the `<currency>->USD` mid rate of `process_date` |
| `amount_usd_source` | Descriptive flag with a closed set of values: `native` (dataset value kept), `same_currency` (USD, amount copied), `daily_rate_fill` (computed from the daily rate) |
| `amount_usd_fx_rate` (optional) | The rate used when `amount_usd_source = 'daily_rate_fill'`, else null; makes each fill auditable in one row |

Rules:

- No `1.0` fallback and no "latest rate" fallback. A non-USD row with no rate for its process date fails the load with a named error (data contract), or lands in a quarantine table with `amount_usd_source = 'unresolved'` if the team prefers a partial load. Recommendation: fail the load; the probe found no such row in 2026 and a silent partial load hides defects.
- Provenance label for filled values: `derived` (`AGENTS.md` section 11).
- `gold_transactions.amount_usd_normalized` becomes an alias of the silver `amount_usd` (or is dropped once the gateway reads the new name) so there is one definition.
- The serving copy in Supabase `bank` publishes `amount_usd` and `amount_usd_source`; `amount_usd_legacy` stays local (minimization, rule 10) unless the console needs it.
- Contract tests (rule 12, labeled fixture): a fixture row with null `amount_usd` and a known rate produces the expected fill and flag; a USD row keeps `same_currency`; a native row keeps `native` and `amount_usd = amount_usd_legacy`; a non-USD row without a rate fails the load. A profile test asserts 0 nulls in `amount_usd` after silver and that every `amount_usd_source` value is in the closed set.
- Report line for the data-quality section: "5 % of COP and ARS charges lack the USD amount; filled from the daily mid rate of the process day, which reproduces the dataset's own conversions within 2 %; USD rows carry no `amount_usd` by design".

This matches what the roadmap already assigns to front A on day 3 ("tipo de cambio por fecha") and the consequence recorded in `AGENTS.md` section 7 ("fill from the daily rate and record the source; fail the load when no rate exists"). The additions here are the flag, the legacy column and the measured evidence.

### 1.5 Effect on the policy engine (spec question P2)

With the cleaning step upstream, the engine receives a USD amount on every real row, so the null branch stops being a customer situation and becomes a defensive guard for malformed calls (the engine is a pure function that tests, the harness or a future caller can feed anything).

Recommendation: keep the guard, and make it escalate to a human with the gap named (`escalation_reason = DATA_GAP_AMOUNT_USD`, `data_quality_flag = MISSING_AMOUNT_USD`) rather than abstain. After the fix, a null reaching the engine means a pipeline defect; an escalation puts it in front of a person and into the report's counts, while an abstention would hide it behind a customer-facing apology. Spec change if accepted: assumption S9 and acceptance criterion 18 in `docs/specs/dispute-policy-v2.3.md` switch from abstention to escalation; the test name stays `test_pol_disp_type_missing_amount_usd_is_data_gap`.

### 1.6 Decisions needed

1. Column names as proposed (`amount_usd`, `amount_usd_legacy`, `amount_usd_source`, optional `amount_usd_fx_rate`), or other names.
2. Missing rate: fail the load (recommended) or quarantine.
3. Fill lives in silver (recommended) or stays in gold with the flag and legacy columns added there.
4. Engine guard behavior: escalate (recommended) or abstain.
5. Owner and day: front A, day 3 per the roadmap; the policy portion does not touch `ingestion.py`.

## 2. Resolutions of the policy spec questions (27 September)

The team answered questions P1 to P7 of `docs/specs/dispute-policy-v2.3.md` on 27 September. Each answer is recorded here with the definition the code will follow, so every front works from the same wording. Anything that reaches outside the policy portion is marked as such.

### 2.1 P1. Secondary clauses and risk explanation

Decision: the engine records every escalation clause that also fired behind the deciding one in `secondary_clauses`, and passes `risk_top_features` (the top SHAP contributions of the fraud model, computed offline) through to the decision so the handoff packet can carry them. The first-match rule of the brief is unchanged. The wider proposal (customer profile, SHAP pipeline, tool loop, console panel) is written up in `docs/specs/customer-profile-risk-explanation-spec.docx` for discussion and lands after G1.

### 2.2 P3. Case memory feeds the deterministic decision, also in fallback mode

Direction from the team: the chatbot must decide deterministically using the customer's previous experience, and the keyword fallback must use the same incremental memory of cases as the Jev path.

Definition:

- The memory is the set of facts the system itself recorded in earlier conversations and cases (`ops.conversations`, `ops.dispute_cases`, `ops.handoffs`, `ops.card_locks`), aggregated per customer by code. It grows with every conversation; every turn writes its signal values and ids, never raw text. Building it is front B work (ops schema, days 4 to 6).
- The policy receives it as typed fields fed by fixtures until the store exists: `prior_distress_max_30d` (highest distress score recorded in the last 30 days, or null), `prior_escalations_180d`, `prior_cases_180d`, `prior_lock_refused` (the customer declined a lock before). The decision echoes them in `case_memory` for the packet.
- `POL-ESC-DISTRESS` escalates when any of these holds: the Jev distress score of the current message is 2 or more; Jev is absent and a distress keyword matches; the memory holds a severe distress flag (`prior_distress_max_30d >= 2`). A low Jev score on the current message does not cancel the memory trigger. Keywords stay a fallback for the current message only, as the brief says.
- Later clauses may read the memory the same way (for example a prior lock refusal shapes the lock question), always as an explicit typed input with a test, never as free text.

### 2.3 P4. Unsupported categories are explicit, and no decision is taken in ambiguity

Direction from the team: the hackathon rewards depth on one topic, so every unsupported category must be spelled out; Jev defines the category with deep context; a guardrail prevents deciding in an ambiguous scenario.

Definition:

- Closed list of out-of-scope categories, one Jev `Choice` when the intent is `fuera_de_alcance`: `prestamo_o_credito` (loans, credit eligibility, limits), `saldo_o_extracto` (balances, statements, movements), `inversion_o_seguro`, `soporte_de_tarjeta` (PIN, replacement, delivery, anything about the card that is not a dispute or a theft), `otro_producto`, `no_determinado`. The keyword extractor fills the same field from a word list when Jev is absent.
- The policy takes `out_of_scope_category` as a typed input. `POL-DISP-TYPE` abstains only when the intent is `fuera_de_alcance` with decisive confidence (0.70 or more, or no confidence value when the keyword extractor runs), and the explanation names the category and where the customer can get help. With confidence under 0.70 the case goes to `POL-CLARIFY` and after two attempts to a human (`POL-ESC-AMBIG`); the engine never abstains on a doubtful reading. This is the guardrail.
- Deep context for Jev (front B, `docs/JEV_TYPESAFE_AI.md`): the Jev state carries the masked messages of the current session plus the profile's topic list and the case memory facts, which are derived values, never dataset rows. This keeps the decided row "Datos que ven los modelos".

### 2.4 P5. Risk-tiered actions and the temporary lock

Direction from the team: before any action the system weighs the risk of that action; the preventive lock is temporary and can be lifted at any time, but each supported action needs a layer of authentication proportional to its risk, and unlocking is the most critical one.

Definition:

- The lock recommendation is independent of the dispute outcome: a stolen-card claim (Jev 0.80 or more, or the keyword fallback) or a multi-charge escalation recommends the lock even when the named charge is out of window or not disputable. The customer confirms with yes or no; a refusal is recorded in the case, the handoff and the case memory.
- Action authentication matrix, declared in the policy as code (`DisputePolicyEngine.ACTION_AUTH_MATRIX`) and enforced by the gateway and the console:

| Action | Risk tier | Required authentication | Who can trigger |
| --- | --- | --- | --- |
| Open dispute case | Low | Valid session | Policy outcome |
| Read-only tools (profile, charges, cases) | Low | Valid session, session `customer_id` filter | Code, or a model proposal validated by the allowlist |
| Escalate with handoff | Low | Valid session | Policy outcome |
| Temporary card lock | Medium | Valid session plus the customer's explicit yes in the same conversation | Policy recommendation |
| Card unlock | High | Step-up: a fresh Supabase login (new token) plus a human agent approval in the console with an audit entry; never from the chat alone | Human agent |
| Approve or reject a credit candidate | High | Agent role in the token, audit entry | Human agent |

- Scope note: the decided actions of 26 September are two, open case and preventive lock. An unlock is a third real action. The definition above keeps it out of the customer chat and inside the human console, so it does not become a second workflow, but the team must confirm it in the decision log before anyone builds it.
- The decision object carries `required_authentication` for its primary action and `card_lock_required_authentication` when a lock is recommended, so the orchestrator cannot forget the confirmation step.

### 2.5 P6. Fallback keyword lists

Agreed as proposed in assumption S8 of the policy spec: short team-written ES/PT lists for distress and stolen card, named constants in the engine, refined during the labeling days (5 and 6). The out-of-scope list of section 2.3 is added as a third constant.

### 2.6 P7. Clause id for the lock rule

Agreed: `POL-AUT-LOCK` names the card-lock rule. It is added to the brief's clause list in the docs commit that closes the portion.

### 2.7 Where each definition lands

| Definition | Policy portion (now) | Other fronts (after G1) |
| --- | --- | --- |
| `secondary_clauses`, `risk_top_features` passthrough | Yes, with tests | SHAP columns (front A), packet and console (fronts B and C) |
| Case memory fields and the memory trigger of `POL-ESC-DISTRESS` | Yes, fixture-fed, with tests | `ops` aggregation and the write of signals per turn (front B) |
| `out_of_scope_category`, decisive-confidence guardrail | Yes, with tests | Jev `Choice` and keyword list for the categories (front B) |
| `POL-AUT-LOCK`, lock independent of outcome, authentication matrix | Yes, with tests | Gateway enforcement, step-up login, console unlock (fronts B and C, pending the decision-log row) |
| Null `amount_usd` guard | Yes: escalation with the gap named (section 1.5) | Cleaning step with flag and legacy column (front A) |


## 3. Loop log of 27 September (autonomous iterations)

Every question the work raised went to the HITL console Questions tab (`data/fixtures/team_questions.json`, TQ-001 to TQ-020) instead of blocking on chat. Iterations, each committed with tests:

1. Team questions queue in `ops` and the console (store, migration 0002, API, Questions tab, seed fixture).
2. ES256 session verification against a JWKS with a local issuer outside production; no shared secret (SEC-03 closed).
3. PII masker for LATAM documents without eating peso amounts (SEC-05); merchant text escaped inside the untrusted tags (SEC-04).
4. Evaluation harness (`src/eval/`) with the 18-case development split, the starter-pipeline adapter as reference baseline, the brief's metrics with denominators and slices, and `reports/eval_dev.md`. First numbers on the dev split: reference baseline 0 of 9 safe automated resolutions and 11 of 18 unsafe outcomes; proposed stack 9 of 9 and 0 of 18.
5. `bank` serving schema (migration 0003) with `business_today()`, `ops.v_product_status` and `ops.v_customer_policy_facts`; `src/data/publish_serving.py` with parity contracts and no `1.0` fallback; CI workflow with a Postgres service; multi-stage Docker image with the React build (built and smoke-run locally).
6. Postgres banking gateway over `bank` and the live views; `DATABASE_URL` switches the API to Postgres for both bank facts and `ops`; the lock writes `ops.card_locks` and reads the effective status back, `bank.products` stays untouched.
7. Risk model pipeline without `fraud_score` (`src/ml/fraud_risk.py`): behavioral features, time split, cost-weighted threshold, rules baseline on the same split, JSON and Markdown report, and a scorer hook that feeds `POL-ESC-ML-RISK` and the handoff's risk explanation. On the June sample (6 training and 3 test fraud rows) the model memorizes the training split and misses the test rows: a pipeline check, stated in the report. Filed TQ-021 (tracking) and TQ-022 (LightGBM plus ONNX versus scikit-learn).

8. Jev wired for real (27-Sep, key received, TQ-017): `src/understand/jev_extractor.py` calls `typesafe-sdk` 0.7.1 with the model pinned to `jev-1.13.0`, one call per turn with four questions (intent, out-of-scope category, stolen card, distress); the state carries only the masked message and the masked earlier messages; the router records the actual tokens in `ops.llm_usage` (about 650 input tokens per call, 0.00003 USD). Verified end to end on the fixture: a distressed stolen-card message came back as intent tarjeta_robada, stolen 0.97, distress 1.45; a loan request as fuera_de_alcance with category prestamo_o_credito.

Waiting on the team (answer in the console): TQ-013 full history load and LightGBM, TQ-010 profile and SHAP after G1, TQ-014 data use in Supabase, TQ-020 Supabase project URL, TQ-016 data-integrity test behavior.


## 4. Answers of 27 September (team, in chat) and what changed

| Question | Answer | Effect |
| --- | --- | --- |
| TQ-001, TQ-003 amount_usd | Keep the proposed column names; fix at silver; gold carries only the needed values with the field already fixed | Done: `silver_transactions` has `amount_usd` (fixed), `amount_usd_legacy`, `amount_usd_source`, `amount_usd_fx_rate`; `gold_transactions` has `amount_usd` and `amount_usd_source`; `amount_usd_normalized` removed everywhere; a gap without a rate fails the load (TQ-002 stays open, the recommendation is implemented) |
| TQ-005, TQ-006 | "ratify all" | The P1 to P7 resolutions and the card unlock as a console action move to Decidida in `docs/PLAN.md` |
| TQ-007 profile | An agent per customer using the customer's available data, with a differentiation between shareable and non-shareable information | Profile record designed with two sections: shareable (segment, country, topics, case status the customer may hear) and internal (case memory, risk facts, lock history: human agent and AI agent only). Built after G1 (TQ-010) |
| TQ-008 Jev input | Jev categorizes the customer's purposes in the chat; a smart agent decides per turn whether to use Jev, another key (Claude) or the offline path | Done: `src/understand/router.py` (deterministic engine router: trivial turns and the lock confirmation never spend a call; Jev only with a key, an available SDK and budget under the 2 USD cap; a Jev failure falls back to keywords and is audited; Claude drafts only with a key and budget, templates otherwise); `src/understand/jev_extractor.py` (adapter contract plus a stub for tests; the real SDK call is wired when the key arrives, TQ-017); Jev's stolen-card and distress signals now reach the policy |
| TQ-009 risk explanation | Only the human agent and the AI agent, never the customer | Already the case in code; recorded as the rule for the profile spec |
| TQ-010, TQ-011, TQ-012 | After G1; Claude Haiku 4.5; rule table | Recorded |
| TQ-013 full history | OK | Full 2023 to 2026 load started to `data/lakehouse_full.duckdb` (separate file); the sample was rebuilt with the silver fix |
| TQ-014 data use | Yes | Recorded; the publish script can load the organizer subset once the Supabase project exists (TQ-020) |
| TQ-015 keys and budget | Max 2 USD per day | `src/llm/budget.py` and `ops.llm_usage` (migration 0004): every external call checks the daily cap and records its usage; over the cap the app uses the offline path |


## 5. Finding: `is_fraud` carries no behavioral signal in this dataset (27 September, full load)

Trained on 2,869,946 transactions (2,871 fraud) and tested on the last 35 percent of days (1,555,062 rows, 1,445 fraud) with the leak-free features of the brief. Gradient boosting: test ROC AUC 0.500, PR AUC 0.001. Rules baseline: test ROC AUC 0.495. The cost-optimal threshold (missed fraud x10) flags nothing, because flagging at random costs more than missing everything. Full report: `reports/ml_full/fraud_risk.md`. Experiment notebook, executed on the full history: `notebooks/02_risk_model_experiment.ipynb` (the leak, the variables, the fraud rate along each variable, mutual information, ROC of the model, the baseline and the leaked score as reference, cost by threshold, permutation importance, score distributions, and a synthetic-label check: the same pipeline reaches ROC AUC 0.868 when the label depends on behavior).

The fraud rate is flat across every pre-authorization feature (full load, 4,425,008 rows, base rate 0.098 percent):

| Feature | Values (rate in percent) |
| --- | --- |
| Channel | POS 0.095, ATM 0.100, Web 0.099, App 0.096, Branch 0.108, Transfer 0.095 |
| Foreign country | no 0.097, yes 0.105 |
| Amount in USD | under 50: 0.107; 50 to 150: 0.097; 150 to 500: 0.099; 500 to 1,000: 0.096; over 1,000: 0.095 |
| Hour of the processing day | night 0.102, morning 0.095, afternoon 0.097, evening 0.096 |
| Merchant category | null 0.097, Food 0.099, Services 0.096, Other 0.100, Transport 0.097, Entertainment 0.106, Health 0.108 |
| Segment | Basic 0.098, Plus 0.099, Premium 0.089, Student 0.103 |
| Status | Approved 0.098, Declined 0.097, Pending 0.089, Reversed 0.080 |

The only column that separates the classes is the leaked `fraud_score`: non-fraud rows score 0 to 30 (mean 15.0); fraud rows score 0.01 to 99.99 (mean 49.5). A score above 30 is fraud with 100 percent precision, but many fraud rows also score below 30, so even the leak gives partial recall.

Probe for hidden structure (same load): fraud does not cluster by customer (78 customers with two or more fraud rows against 87.4 expected if fraud were independent per row; 130,282 customers with none, 4,155 with one, 73 with two, 5 with three); a prior fraud on the account does not raise the rate (0.089 percent after a prior fraud, 0.098 percent without); gaps between a customer's fraud rows are 56, 288 and 679 days at the 10th, 50th and 90th percentiles; `response_code`, `transaction_category`, `transaction_type`, `product_type` and `transaction_country` are flat. A prior-fraud feature would add nothing.

Cross-table search (27-Sep, `notebooks/03_fraud_signal_search.ipynb`, auxiliary lakehouse built by `scripts/data_ops/load_aux_tables.py`): customers (segment, status, credit score, marketing consent, city), products (opening channel, linked app, credit limit, delinquency), raw transaction columns (category, response code, weekday, city, geolocation), complaints after the charge, call center interactions in the 14 days around the charge (volume, complaints, escalations, negative sentiment, interactions before the charge), transcripts within 7 days (the dataset's intents and topics, plus a categorization of the masked transcripts with the real Jev, jev-1.13.0, 1,013 transcripts, zero keyword fallbacks: every transcript came back as consulta_general with a distress score of 0.01 near normal and near fraud charges alike, which agrees with the dataset's own intent labels, 94 to 95 percent consulta_general in both groups), digital events in the 7 days before the charge (events, logins, other authentication events, IP countries, foreign IPs, platforms, browsers, mobile share), campaign sends in the 30 days before (opens, foreign opens, clicks) and satisfaction surveys (count, detractors, mean score). 140 bins examined; no bin with at least 1,000 rows lifts the fraud rate by 1.5x or more (largest: 1.29 on campaign clicks with 1,038 rows, 1.27 on a survey score of 3 with 2,849 rows, both sampling noise). Nothing qualifies for the model.

Consequences:

1. Hypothesis 3 of `docs/PLAN.md` (a leak-free model beats the rules baseline on held-out data) cannot be confirmed on this dataset. The honest report says so with these numbers: the label is independent of the behavior the model can see, so any lift would come from the leak. This is the data-quality finding the judges ask for, next to the leak itself.
2. `POL-ESC-ML-RISK` stays in the policy as the contract for a risk score, but no calibrated score from this data exceeds 0.70. The API loads no model by default (`models/fraud_risk.joblib` is absent; the full-history model is `models/fraud_risk_full.joblib`, gitignored) so the policy sees a risk of 0.0 and never escalates on this clause, which the report states.
3. Options for the learned component, filed as TQ-023: (a) report the negative result and keep the pipeline as the reproducible evidence; (b) train the same pipeline on a proxy target with real structure in the data, if one exists (to be probed); (c) keep the rules baseline as the deployed risk signal and say why.

## 6. Finding: fraud claims, fraud flags and call transcripts do not touch each other (28 September)

Two questions from the team on 28-Sep: how many transactions are claimed as fraud versus how many carry the `is_fraud` flag (a data issue check), and whether an NLP pass over the call transcripts finds anything fraud related that could enrich the model's data. Evidence in `notebooks/04_claims_vs_flags_and_transcript_nlp.ipynb` (charts `notebooks/16_claims_vs_flags.png` and `notebooks/17_transcript_nlp.png`), on the full 2023 to 2026 lakehouse plus the auxiliary tables. Everything below is aggregate; no customer row or text row leaves the lakehouse.

### 6.1 Claims versus flags

The claim of fraud in this dataset is the complaint subcategory `Cargo no reconocido` under the category `Transactions`. Volumes over the three years: 4,316 fraud flags against 12,297 unrecognized-charge claims (13,580 complaints in the Transactions category, 67,095 complaints of any kind), a stable ratio of about 2.7 to 3.2 claims per flag every year. The ratio itself is not the problem. The problem is that the two populations never meet:

- A flagged charge is not followed by a claim more often than an unflagged one: 0.35 percent of flagged charges have an unrecognized-charge claim from the same customer in the next 60 days, against 0.45 percent of a 1 percent sample of unflagged charges (Fisher exact odds ratio 0.77, p 0.40). Any complaint at all in 60 days: 1.8 percent after a flag, 2.4 percent otherwise.
- The mirror check is flat too: 0.12 percent of unrecognized-charge claims have a flagged charge on the customer in the 60 days before, the same as branch, fee, service and technical complaints (0.08 to 0.22 percent; chi-square over the ten complaint kinds p 0.86).
- Customers with at least one flag ever file unrecognized-charge claims at the same rate as customers without one (7.96 versus 7.92 percent of customers, 0.081 versus 0.083 claims per customer).
- Only 3 claims name the product of a flagged charge inside the window, and none of them matches the charge's amount or currency.
- The complaints table is uniform by construction: every category has 13.2k to 13.6k rows and exactly one subcategory, the description field has five templates and no fraud word, and `origin_interaction_id` is empty in all 67,095 rows.

Reading: `is_fraud` and the complaints table were generated independently of each other and of customer behavior. A claim rate metric (claims over flags) is an artifact of two uniform generators and should not appear in the report as a business number. This is the same independence found in notebooks 02 and 03 (section 5, TQ-023), seen now from the claims side.

### 6.2 NLP over the call transcripts

- The corpus: 171,321 transcripts from 101,951 customers, all Spanish, built from 42 customer templates and 42 agent templates combined into 546 distinct full texts (one template alone covers 30 percent of the calls). Vocabulary: 32 customer words of three or more letters, 72 words in the full texts, all about balances, savings accounts and credit cards. The dataset's own `detected_intents` is `consulta_general` in every filled row, `detected_keywords` is a permutation of "banco, servicio, cuenta", and TF-IDF per topic returns the same eight words for all six topics.
- A Spanish and Portuguese fraud lexicon (fraud, theft, cloning, unrecognized, unauthorized, scam, phishing) hits zero rows in the customer text, the agent text, the full text, the keyword field, the 67,095 complaint descriptions (five templates) and the 101,196 filled survey comments (13 templates).
- Near flagged charges: within ±7 days the template and topic mix differs only at the edge of noise (69 transcripts, permutation p about 0.06, driven by a 23 versus 13 percent share of the "Técnico" topic); at ±30 and ±90 days and in the call center interactions table (four times more rows) the mix returns to the population mix (p 0.23 to 0.71). Sentiment score, negative share and escalation rate are the same next to flagged and unflagged charges. The real Jev already categorized the 1,013 transcripts near sampled charges as `consulta_general` with a flat distress score (section 5).

Reading: there is no fraud content in the calls to bring into the model. Text signals for risk will have to come from real utterances. In this product that source is the chat itself: Jev types every masked message (intent, out-of-scope category, stolen card, distress) and those signals already feed the policy, the handoff packet and the profile; when real transcripts exist, the same four Jev questions apply to them without changes to `src/understand/`.

### 6.3 Consequences and open question

1. The report states, with these numbers, that the label, the claims and the calls are mutually independent in this dataset, next to the leak in `fraud_score` (AGENTS.md section 7). Together with section 5 this closes the search for a learnable fraud signal in the data as delivered.
2. No metric of the proposed stack depends on it: the policy funnel (`docs/specs/dispute-policy-v2.3.md` phase 3) and the evaluation harness (`reports/eval_dev.md`) use the dispute window, amounts, velocity and the customer's message, none of which is the label.
3. Filed as TQ-025 for the mentors: confirm that `is_fraud`, the complaints and the transcripts are synthetic and independent, or point to the linkage we missed (for example an id that ties a complaint to a transaction). If a linkage exists, notebook 04 reruns as is.

## 7. Decision proposal: the fraud risk score comes from a model transferred from the IEEE-CIS competition (28 September)

Sections 5 and 6 leave `POL-ESC-ML-RISK` without a trainable target: `is_fraud` carries no learnable signal (its rate is flat across every feature) and `fraud_score` is derived from it. The team proposed bringing a model from a Kaggle fraud competition. The variable mapping and the approach are in `docs/specs/fraud-risk-model-v1-ieee-cis.md`; the summary:

1. Competition of record: IEEE-CIS Fraud Detection (Vesta data, 590,540 labeled card-not-present transactions, 3.5% fraud, metric ROC AUC). Its winning recipe is client-id aggregation (a uid built from `card1`, `addr1` and the normalized `D1`, then amounts and counts aggregated per uid respecting time). Our client id is native (`customer_id`, `product_id`), so that recipe is the cheapest part of the transfer.
2. What maps: amount in USD, processing-clock time, credit or debit card, card age, days since the previous charge, counts per card and per customer in 1, 7 and 30 days, expanding mean, std and z-score of the amount per card, ratio to the customer's average, an address distance bucket (same city, same country, abroad), the consistency checks (the `M` flags), the email domain frequency and card-not-present.
3. What does not map: the identity table (device, browser, IP). `digital_events` cannot be tied to a charge: of 205,943 Web and App charges of 2026, 170 have an event of the same customer within an hour and none on the same product the same day, and `ip_country` never differs from the home country. Also excluded: `ProductCD` (undisclosed codes), the card network, the recipient email and the Vesta `V` columns beyond what per-card aggregation reproduces.
4. Approach: one feature contract computed identically from both sources, the model trained and validated on the competition's time split, an adversarial validation that measures the domain gap, and a percentile threshold computed on our serving window (top 2% of disputable charges) in place of the absolute 0.70. The `RiskScorer` interface, the orchestrator and the clause ids do not change. Our label is used once, to report its flat agreement, never to train.
5. Limitation to state: the competition holds card-not-present rows only, so on POS, ATM and Branch charges the model extrapolates and the rules baseline stays as the second opinion.
6. Filed as TQ-026 for the mentors: confirm the transfer as the model of record, the data licence for the submission, and the percentile threshold. Until then the policy keeps `ml_risk_score = 0.0` by default (TQ-023 stands).

### 7.1 Results of notebook 05: feature and level homologation (29 September)

`notebooks/05_ieee_cis_feature_homologation.ipynb` (charts 18 to 21) computed the contract on both sources and put the categorical levels to Jev; details in section 10 of the spec.

1. The contract is computable on both sides. On the competition side the features carry signal (best univariate AUC 0.56 to 0.68 for card age, credit or debit, days since the previous charge, amount, consistency checks); on the bank side every one sits at 0.50.
2. Contract v1.1: five features kept as they are, four kept as per-source ranks (amount, log amount, days since the previous charge, mean amount per card), eleven weak ones decided by the ablation, `cards_per_customer` bank-only, `card_not_present` and `email_domain_freq` dropped (constant on one side each; the email frequency fingerprints the source).
3. Domain gap: raw values separate the sources perfectly (adversarial AUC 1.000, null patterns and discrete values fingerprint the source); on per-source percentile ranks it is 1.000 as well, also with the continuous features only (tie masses fingerprint the source). The gap cannot be transformed away; the transferred probabilities mean nothing in absolute terms on the bank side, which is why the threshold is a percentile.
4. Levels (Jev, 61 typed answers, cached): credit and debit map to Tarjeta Crédito and Tarjeta Débito at 0.99; browsers and most OS families map; the card network, the product codes C, H, R and S, the ISP email domains and Internet Explorer or Opera have no equivalent; left to a human: `ProductCD` W (0.63 no equivalent versus 0.31 Purchase), DeviceType mobile, Windows, Linux, msn.com, yahoo.com.mx, me.com.
5. Coverage: Jev marks Web (0.69) and App (0.60) as the competition's kind and every other channel below 0.05, so the transferred score is served on Web and App charges (30.0% of charges) and the rules baseline on the rest. TQ-026 context updated.
6. Data quirk: 18.71% of charges predate the opening date of their product (product opening dates are independent of the transactions); recorded in AGENTS.md section 7.

### 7.2 Decision: the model trains only on deployable variables; first transfer results (29 September)

1. The team decided that the trainer uses only the variables the deployed app can compute at scoring time from the serving copy. Of the contract, only `card_age_days` fails that test (opening dates independent of the charges, 7.1 item 6); the 19 remaining features are `DEPLOYABLE_V1`.
2. Trained on the competition's time split with per-source percentile ranks: holdout ROC AUC 0.817, PR AUC 0.165; without the per-card aggregates 0.785, without the discrete block 0.755. Calibrated on 75,366 Web and App charges of the last 60 days: threshold 0.0669 (percentile 98, 2.0% flagged); agreement with the bank label 0.507, flat as expected.
3. Wired into the stack: the policy clause reads the threshold from its input (default 0.70), the orchestrator passes the bundle's percentile threshold and the handoff shows it, and the API loads the transferred scorer by default. Spec sections 8 and 11; TQ-026 keeps the mentors' confirmation open.

### 7.3 Feature importance over the whole competition (29 September): what to cherry-pick for deploy

`scripts/notebooks/ieee_cis_feature_importance.py` trains on all 415 usable competition columns (holdout ROC AUC 0.917 against 0.817 for the deployable contract) and measures the AUC lost when each column, and each column family, is shuffled; `reports/ml/ieee_cis_feature_importance.md` lists the top 40 with their meaning and the way to obtain each at deploy.

1. The largest block is the C counts (0.063 AUC), ahead of the 339 Vesta columns (0.045), the D time deltas (0.037) and the card attributes (0.030). Counts and deltas are bank-side history (distinct products per customer, distinct cities and merchants per card, days since the first charge in a city or on a channel), so most of the gap to the all-column model is reachable from the serving copy.
2. Askable in the chat as Jev typed answers: the match flags (is the card with you, is the address on file current), the distance (were you in the city of the charge), the device and, for transfers, whether the recipient is known.
3. Login telemetry (device, OS, browser, IP, proxy) is the counterpart of the identity table; worth capturing at login for the next model version.
4. Next step, once the team picks: add the chosen bank-side counts to the contract (v1.2) with the same no-look-ahead tests, and the chosen chat questions to the Jev question set with their calibration measured per language.

## 8. Answers of 29 September (Kmilo, in chat) and what changed

| Question | Answer | Effect |
| --- | --- | --- |
| TQ-021 experiment tracking | MLflow | Done (1-Oct): `src/ml/fraud_risk_transfer.py` opens one MLflow run per training (experiment `fraud_risk_transfer`) with params, metrics, ablations, bank calibration, the commit tag, and the JSON and Markdown reports plus the bundle as artifacts. Store: `sqlite:///mlflow.db` with artifacts in `mlruns/` (MLflow 3 retired the plain file store, so `sqlalchemy` and `alembic` joined `mlflow-skinny`); no server. The suite tracks into a temporary store |
| TQ-024 intent confidence | Keep the per-option confidence; intents stay independent, always. When a message carries several intents, the clarification lists each one to the customer and asks them to clarify each separately; never merge them into a dispute mass | Spec criterion 8 unchanged. Pending: the orchestrator's clarification turn lists the detected intents (today it asks a single generic question); test first |
| TQ-026 risk model | Accept the IEEE-CIS transfer. `POL-ESC-ML-RISK` escalates to HITL by the percentile threshold of the serving window, not the fixed 0.70. Model of record on the homologated variables only. Follow-up: cherry-pick, among the roughly 400 competition variables left out, the ones the agent can consume so the score improves after the interview with the customer (section 7.3) | Already wired (commit 756fe10). `docs/PLAN.md` row moved to Decidida. The competition data licence stays a question for the mentors |
| TQ-020 Supabase project | Created by Daniel: `https://lrddokaihdwrdtwfiale.supabase.co` | JWKS verified on 29-Sep: one ES256 P-256 key, as `SessionVerifier` expects. Pending: personas with `app_metadata.customer_id` and `app_role`, front login through `supabase-js`, `SUPABASE_URL` in each environment |

## 9. Proposal: a risk zone validator beside the risk score (3 October)

Kmilo asked (3-Oct, chat) for a layer that works as a parallel validator of whether a transaction is in a risk zone, next to the model's high-probability flag. What was built, what the data supports and what stays open:

1. Definition. `src/tools/risk_zone.py` reads the identified charge with no model: where it was made against the customer's country and city on file. Zones: `HOME` (the customer's city, or their country when a city is missing on either side), `DOMESTIC_OTHER_CITY`, `ABROAD` and `UNKNOWN` (no country on the charge or on the profile). The risk zone is `ABROAD`. Zones are relative to the customer because the data holds a country and a city per charge and nothing finer (28 cities, coordinates 81% null), and no label can rank places: `is_fraud` carries no learnable signal (section 5), so a fraud rate per city is noise. A map of risk zones inside a city needs an external source, cited and labeled (rule 4); none is used.
2. Parallel, with code of its own. The validator takes what the scorer takes (the charge, the customer's rows, the profile) and shares no code with it. A test pins its zones to `address_distance_bucket`, the feature the model computes on its own: 0 disagreements on the 251,398 charges of the window. It reads every channel, the 70% the model does not score included.
3. What it does today. Every turn that identifies a charge writes the audit row `RISK_ZONE_VALIDATED` (the zone, the places, the customer's earlier charges in that place among the rows read, and the cross-check with the model: `BOTH`, `MODEL_ONLY`, `ZONE_ONLY` or `NEITHER`), and a handoff carries the line "Risk zone check: ..." among its verified facts. It changes no outcome and never reaches the customer (TQ-009 keeps risk explanations with the human agent). `get_orchestrator` wires it in the API; the evaluation harness builds its orchestrator without it, so the held-out results do not move.
4. Measured on the 60 days to 2026-06-17 (`data/lakehouse_full.duckdb`, derived from the organizer's data, with the served bundle):

| Measure | Value |
| --- | --- |
| Charges in the window, all channels | 251,398: 95.1% `HOME`, 0.3% `DOMESTIC_OTHER_CITY`, 4.6% `ABROAD`, alike on every channel (4.5% to 4.9% abroad) |
| Web and App charges, the ones the model scores | 75,366: 1,508 above the threshold (2.0%), 3,441 abroad |
| Cross-check on those | both flag 180, only the model 1,328, only the zone 3,261, neither 70,597 |
| Abroad and above the threshold | 5.23% of the abroad charges against 1.85% of the rest: the model already weighs the place, and 94.8% of the abroad charges stay under its threshold |
| Channels the model does not score | 176,032 charges (70.0%), 8,120 of them abroad (4.61%), which no risk check read before |
| Abroad and at or under 500 USD | 2.46% of the window: what an escalation rule would move from intake to a human |

5. Open, TQ-038: what a charge in a risk zone should trigger. Advisory as today, a new mandatory escalation clause, or the preventive lock offer with the customer's confirmation (a new reason code in the `ops.card_locks` CHECK and a migration). The last two change policy v2.3 (spec, traceability matrix, policy corpus) and the outcomes of the frozen held-out suite. A hold of the payment at authorization time is not on the list: the dispute flow acts after the charge, and a second workflow breaks rule 1.

## 10. Sibling charges: the other charges of one card at one merchant on one process day (3 October)

Kmilo asked on 3-Oct how the system could react when a point of sale repeats charges on a card in one night. Stopping a payment is outside the workflow (two real actions: open a case, and the card lock the customer confirms; rules 1 and 8), so the part that fits is what the dispute turn tells once the customer disputes one of those charges. In code on branch `feat/sibling-charges`; the open point is TQ-039.

### 10.1 What the data allows

Measured on `data/lakehouse.duckdb` (the June 2026 sample, 11,703 rows) on 3-Oct:

| Question | Result |
| --- | --- |
| Is there a terminal or point-of-sale id? | No. `gold_transactions` holds `merchant_name`, `merchant_category`, `transaction_city` and `transaction_country`, nothing finer |
| How many merchants are there? | 25 names; "Unknown Merchant" covers 9,113 rows (77.9 %) |
| Does a card repeat a merchant on one process day? | Purchases per card, merchant name and process day: 2,722 groups hold one purchase, 1 holds two |
| Does a card hold a burst on one process day? | Transactions per card and process day: 11,567 groups hold one, 68 hold two, none holds three |
| Is there a label to check a burst against? | No: `is_fraud` carries no signal (section 5) |

So the behavior cannot be measured on the supplied data. It is shown on team-generated fixtures only (rule 12), and the tests label their rows that way.

### 10.2 Definition

A sibling of the identified charge is another charge of the same customer that shares its `product_id`, its merchant name and its bank process day (`process_date`, so a night that crosses midnight stays in one day), is disputable (`POL-DISP-TYPE` and `POL-WIN-60` as the gateway row tells them), has no open case, and was not named in the customer's message. A charge with no merchant on record has no siblings: two "Unknown Merchant" rows are not one merchant. The siblings come from the 25 most recent charges the gateway already read for the session's customer, so no other customer's data is involved and no new bank read is made.

### 10.3 What the turn does with them

| Outcome of the turn | Customer | Human agent |
| --- | --- | --- |
| Case opened and verified | After the case number, the reply names the merchant, lists the siblings' amounts and invites the customer to write the amount of any other charge they do not recognize | Audit row `SIBLING_CHARGES_LISTED` with the transaction ids |
| Escalation | Nothing added to the reply | One verified fact in the handoff packet: how many siblings and their ids |
| Clarification or abstention | Nothing | Nothing |

They are told, never counted. `POL-ESC-MULTI` counts distinct disputed charges in 48 hours (spec v2.3), and a charge the customer has not disowned is not disputed, so `recent_disputed_charges_count` is unchanged and no clause, threshold or order moves (spec assumption S20). When the customer then disputes a sibling, the existing flow opens its case, and the third disputed charge reaches `POL-ESC-MULTI` with the lock offer as before.

### 10.4 Effect on the evaluation

Both suites were run before and after the change from the same base commit of `main` (rules-only, one repeat, no risk model in the checkout): every metric of both systems is identical. On the development split no reply changes. On the held-out suite the replies of four cases of the category `high_value_or_multi_charge` (HO-153, HO-154, HO-157, HO-159) gain the note in the two turns that open a case before the third charge escalates; their outcomes are the same. The check was repeated with the branch stacked on the risk zone validator of section 9, with the same result. No threshold was tuned on either suite.

### 10.5 Open question (TQ-039)

Should a burst of siblings also escalate the turn with the lock offer, as three disputed charges do? Recommendation: not now. Counting charges the customer did not dispute would send customers with several legitimate purchases at one merchant to a human, it is a spec change (a new input for `POL-ESC-MULTI` or a new clause), and no data can calibrate the size of a burst.

## 11. Proposal: gold tells a merchant that does not apply from one that is missing (4 October)

Kmilo asked (4-Oct, chat) why so many charges read "Unknown Merchant", whether the data holds anything else that names where a charge was made, and for gold to say "Not Applicable" on the internal transactions. What the data shows, what changed and what stays open:

1. Finding (`data/lakehouse_full.duckdb`, derived from the organizer's data). `merchant_name` is NULL on 76.7% of the 4,425,008 transactions, and the gap follows the charge type, not chance:

| Transaction type | Rows | Without a merchant |
| --- | --- | --- |
| Purchase | 1,083,406 | 54,172 (5.0%) |
| Withdrawal | 964,673 | all |
| Transfer | 896,438 | all |
| Payment | 738,964 | all |
| Deposit | 609,409 | all |
| Adjustment | 132,118 | all |

The five types carry no merchant and no merchant category on any channel, so on them the field does not apply. The 5.0% of purchases without one is a real gap (the dictionary's null trap). These rates come from the lakehouse: the held-out file holds fabricated charges and gives other ones.

2. Definition. `gold_transactions.merchant_name` is never NULL and has three readings: the name; `Not Applicable` on a Withdrawal, Transfer, Payment, Deposit or Adjustment without one; `Unknown Merchant` on any other charge without one (a purchase that lost it, or a type the dataset does not have). A name is never replaced, and the list of types is explicit, so a new type is not declared merchant-free by default. `merchant_category` stays NULL as before: the risk model reads it, and its features must not move. `tests/test_ingestion.py` pins the rule.

3. Who reads gold. Not every path, so the label alone does not reach the agent everywhere:

| Path | What the gateway reads | When the new label arrives |
| --- | --- | --- |
| Local API without `DATABASE_URL` | `gold_transactions` and `gold_customers` on each turn that reads the bank (the card list and the lock use `silver_products`) | When gold is rebuilt (no S3 needed, the command is in `CLAUDE.md`) |
| Deployed API (Vercel) | Postgres `bank.*`, a copy of gold made by `src.data.publish_serving`, plus the live `ops` views | When the serving copy is published again; until then it keeps "Unknown Merchant" |
| Evaluation harness | A bank fixture built from each JSONL case | Never for the frozen held-out suite: its charges without a merchant keep "Unknown Merchant" |

So the orchestrator reads both labels as "no merchant" when it looks for a merchant hint in the message, and the held-out builder reads `Not Applicable` back as the label suite v1 was frozen with: rebuilt from the relabeled lakehouse, the suite reproduces its recorded SHA-256. A turn the policy explainer answers does not read the bank at all.

4. Effects. No policy outcome moves: the label was never an input of the policy, and the merchant hint already ignored placeholder labels. What the customer sees does move on the local path: the list of recent charges and the option buttons print the label as it is, so a withdrawal now reads "Not Applicable" where it read "Unknown Merchant", in English either way.

5. What else names where a charge was made (the answer to the address question). The source has no merchant id, terminal or merchant address. It does have three columns that gold does not carry today:

| Column | Coverage | What it gives |
| --- | --- | --- |
| `branch_id`, joined to `branches` (350 rows: name, type, address, city, state) | 95% of the ATM and Branch channel charges (1,387,932 rows, 31.4% of all), every one resolves; NULL on POS, Web, App and Transfer | Not the place of the charge: always a branch of the customer's country, but its city equals the charge's own `transaction_city` on 17.5% of the rows that have one (217,964 of 1,248,917). It cannot be shown to the customer as where the charge was made |
| `transaction_category` | 95% of payments and of purchases (Food, Services, Entertainment, Transport, Health, Other); NULL on the other four types | What a payment was for |
| `transaction_city`, `transaction_country` (already in gold) | 90% and 100% | Where it was made |

Of the 136,032 disputable charges without a merchant in the 60-day window (Payment, Withdrawal, Transfer), 90% have a city; 31.3% have a branch, which the row above rules out as a place.

6. Open, TQ-040: how a charge without a merchant reaches the agent and the customer. The label is text inside a name column, so every reader has to compare strings to know it is not a name (the orchestrator and the held-out builder do so today). The proposal is a typed field beside the name, computed once and returned by both gateways (`merchant_status`: `named`, `missing`, `not_applicable`), so the rule holds on every path of item 3, and a description of the charge built from what the data does have (the type in the customer's language, the payment category, the city) for the charge list and the handoff. That text reaches the customer, so the team decides it.

## 12. Topics: a message with several statements is taken one by one (5 October, TQ-044)

Decided by Kmilo on 5-Oct, after the Jev measurement of the same day. It carries TQ-024 (intents stay independent, never summed) into how the message is read and answered.

**What was wrong.** Jev was asked to pick one intent among five. "Roubaram meu cartão e agora vejo uma compra de 2.282 dólares que não fiz" holds two true statements, so the answer split (0.64 for the stolen card) and fell under the 0.70 of `POL-CLARIFY`: the customer got a question and no human saw a charge above 500 USD. Six held-out cases turned unsafe that way. The keyword extractor had its own gap: a request made beside a dispute either hid the dispute ("... y necesito un préstamo" read as out of scope) or went unanswered ("... Dame mi saldo.").

**The rules.**

1. Each statement is a topic, read on its own. `src/understand/topics.py` defines each topic in full: what it is, what counts and what does not.
2. Topics have a criticality: the card lost or stolen (1), a charge dispute (2), a question about the rules (3), a request this channel does not handle (4).
3. With more than one topic the reply says they are taken one by one, starting with the most urgent. The conversation still asks one thing at a time: the state is the topic being asked, so no parallel states are needed.
4. The number of topics goes to the message signals (`topic_count`) and to the audit row `TOPICS_DETECTED`. It is never shown to the customer.
5. A request this channel does not handle is named as such while the dispute goes on. Alone, it keeps the abstention it always had.
6. A loan installment disputed in one clause ("el cobro de la cuota del préstamo") stays out of scope: the request has to sit in a clause of its own, and ask for something, to count as a second topic.

**Jev.** One yes or no question per statement (`dispute`, `stolen_card`, `other_request`), plus the category of the other request and the distress score. The intent the policy reads follows from them, and its confidence is the probability of the dispute statement, so `POL-CLARIFY` keeps its 0.70 with a cleaner input. No threshold changed.

**Measured** (`reports/jev_evaluation_report.md`): with Jev, unsafe outcomes go from 26 of 250 back to 20 of 250, the keyword figure; exact outcomes are 223 of 250 against 221. Rules only, every held-out case keeps its outcome; 11 replies gain the one-by-one line.

**Left open.** The reply names the specialist before the lock offer although the lock is the pending question; and a list of open items per conversation (an agenda) would make the one-by-one order explicit for any pair of topics. Both are for after the submission.

