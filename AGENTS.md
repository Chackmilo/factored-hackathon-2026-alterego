# AGENTS.md

Instructions and context for AI coding agents (and new teammates) working in this repository.
Read this file before touching code. It consolidates the team Notion workspace, the team brief,
the official hackathon rules and the current state of the codebase as of 2026-09-26.

## 1. What this repo is

Team submission for the **Factored AI & Data Hackathon 2026**. The challenge: build an
**AI-first banking customer-service system** (not a chatbot) for one focused workflow, end to end,
with mandatory support for **Spanish and Portuguese**.

Proposed workflow (team decision still pending, see section 10): **transaction-dispute intake**.
The agent finds the disputed charge, checks policy eligibility, opens a well-documented case and
protects the customer when needed. It never refunds or moves money.

Expected flow for every interaction: **Understand -> Decide -> Act -> Verify -> Escalate**.

## 2. Sources of truth

Read these before inventing anything. Content in them was written by the team or the organizers.

| Source | What it holds |
| --- | --- |
| Notion: Factored Hackathon 2026, AI-First Banking Agent (parent page) | Key dates, links to official docs, subpages below |
| Notion: Scope e informacion no tecnica | Full summary of the official problem statement, judging criteria, metric definitions, logistics |
| Notion: Task | The five-stage flow, the three case types, the four candidate workflows and their comparison |
| Notion: Data y data dictionary | Dataset summary, all 13 tables and columns, FK relations, profiling findings, project implications |
| Claude Doc: Factored Hackathon 2026 Team Brief | The team's original proposal: rationale, architecture, evaluation plan, first 10-day plan |
| `docs/TEAM_BRIEF_COMPLEMENTED.md` (v2.1) | Dispute policy spec with clause ids, data contracts, handoff packet, held-out suite, metric formulas. Supersedes the original brief on these topics |
| Official Problem Statement (Google Doc) | https://docs.google.com/document/d/18AwONT8hQupRcfNPLFrPo6fHOJ_OUn1nBf-3jMnla2c/edit |
| LATAM Bank Dataset Summary (PDF) | https://drive.google.com/file/d/1V7n9v0zuv9SYzpW2AzPnssgAp5X_buXc/view |
| LATAM Bank Complete Data Dictionary (PDF) | [link to the organizer's data dictionary removed] |
| `docs/*.pdf` | Local copies of the official statement, kickoff slides, dataset summary and dictionary (git-ignored: the dictionary holds AWS keys) |

**Precedence when sources disagree:** official problem statement and kickoff slides, then the section 4
rules, then the complemented brief, then the code. Code that disagrees with the brief is a gap to plan
(section 9), not a spec change.

Notion parent page: https://app.notion.com/p/3e67b60f246881a3b780c10c7eff38c5
Team brief: https://claude.ai/code/artifact/025bdc1c-573c-45a2-b3fd-82e7ae558f19

Team coordination happens in the hackathon Slack. Mentor questions go to `#technical-help`.

## 3. Key dates

| Milestone | Date |
| --- | --- |
| Challenge launch, 10-day build starts | 2026-09-25 |
| Submission deadline | 2026-10-05 |
| Finalists announced | 2026-10-15 |
| Award ceremony | 2026-10-16 |

## 4. Non-negotiable rules from the official brief

Violating any of these disqualifies the work, not just the feature. Enforce them in code review.

1. **One workflow, deep.** Extra workflows earn no bonus. Depth and engineering judgment score.
2. **Three case types must be demonstrable:** normal automated resolution, ambiguous or
   unsupported request (clarify or abstain), and human-required (structured handoff).
3. **Spanish and Portuguese** interactions must be demonstrated. Report language-coverage limits
   honestly (the dataset has no Portuguese).
4. **Justify the workflow with the supplied data.** Use only organizer-approved data. Label every
   artifact as real, de-identified, synthetic or team-generated.
5. **Identity comes from a trusted test session** (mock OIDC/JWT or an identity service). A
   document number or customer number alone never proves identity.
6. **Permissions and policy live in the tool or service layer,** never in model prose or prompts.
   The model proposes; deterministic code disposes.
7. **Report only actions whose outcome was verified** by reading back from the system of record.
8. **No real money movement, no real credit decisions.** Provisional credit is at most a simulated
   recommendation inside the human handoff packet.
9. **Hidden model chain-of-thought is not an audit artifact.** Explanations must come from
   sources, policy rules and execution records.
10. **No credentials or private records** in public submissions or in calls to external models.
    The data dictionary PDF contains read-only AWS keys: keep them in a git-ignored `.env`, never
    in code, prompts, logs or Notion.
11. **Be honest about what is missing:** capacity limits, data limits, language coverage,
    deployment work, remaining risks.
12. If data is static, prove update correctness with a clearly labeled **test fixture**.

## 5. Judging

From the kickoff slides: *First and foremost, the solution must work.* Then:

- General rationale and documentation
- **AI Engineering:** backend, frontend, deployment
- **Data Analytics:** data quality and relevant insights
- **Data Engineering:** extraction and transformation
- **Machine Learning:** model selection, optimization, implementation, tracking

No single skill is mandatory, but multidisciplinary coverage is expected. Every team is judged on
data engineering and AI/ML rigor even when using pretrained or retrieval components (component
selection, intent or relevance labels, representations, leakage prevention, held-out evaluation,
error analysis).

### Metrics we must report

Compare **baseline vs proposed system on the same held-out workload**. Report case count and mix,
label quality, model and prompt versions, run-to-run variability, and the failures.

| Metric | Definition |
| --- | --- |
| Safe automated resolution | Eligible case reaches the correct, policy-compliant outcome with no human. Rate over all in-scope cases, plus the share where automation was attempted. |
| Containment | Case ends without transfer. On its own it does not prove the problem was solved. |
| Escalation quality | Cases needing escalation are transferred well with useful context. Report missed and unnecessary transfers. |
| Unsafe outcomes | Unauthorized disclosures or actions, or materially wrong results, as counts over denominators. Zero failures on a small set does not prove zero risk. |
| Operating efficiency | End-to-end p50/p95 latency; cost per attempted case and per successful automated resolution. State workload, sample size and cost assumptions. Use "not defined" when there are no successes. |

Slice results by **language** (ES vs PT), **country** and **authorized customer segment**
(Premium, Plus, Basic, Student) with small-sample caveats. If an LLM judge is used, document its
rubric and validate a sample against human or deterministic judgments. Never present offline
results as production improvements.

### Held-out suite must include

Normal disputes, ambiguous charges, out-of-window requests, human-required cases, plus these failure
types: incorrect or missing data, expired sessions, unauthorized access attempts, prompt injection
(for example a merchant name that says "ignore instructions"), tool failures, multilingual ambiguity.

## 6. The workflow: transaction-dispute intake

Why disputes (from the data): "Queja" (complaint) contacts have the worst first-contact resolution
(43.6% vs 91.5% for transactional), 63% need follow-up and average 7.2 minutes. "Cargo no
reconocido" (18.3%) plus "Cobro indebido" (18.2%) are about 36% of all complaints.
`transactions.is_fraud` gives a real label for ML.

| Case | Example | Expected behavior |
| --- | --- | --- |
| Normal | "No reconozco un cargo de ayer en Super Ahorro" | Find the transaction, check the dispute window, open the case, read it back, confirm |
| Ambiguous | "Tenho uma cobrança estranha" with several candidate charges | List options and ask. Out of window: explain the policy and abstain |
| Human required | High amount, several unrecognized charges, or high ML risk score | Handoff packet of verified facts; preventive card block when a stolen card or multi-charge fraud is claimed |

Allowed real actions (proposed): **open dispute case** and **preventive card block**. Nothing else.
Preventive block is part of disputes, not a second workflow. The other three candidate workflows
(account/payment inquiries, card support, credit eligibility) were evaluated and rejected; credit
eligibility is the fallback. See the Notion "Task" page for the comparison table.

## 7. The data

**LATAM Bank Dataset v1.0.0**, 100% synthetic, no real customers. About 19M rows in 13 tables.
Mexico, Colombia, Argentina (**no Brazil**). Period 2023-06-17 to 2026-06-17. Currencies MXN, COP,
ARS, USD with daily USD conversion. **All text is Spanish** (Mexican, Colombian, Argentine
accents). **No Portuguese anywhere.**

Storage: S3 `us-east-2`, CSV, fact tables partitioned `year=/month=/day=` (about 5.3 GB, about
7.7k objects). A `data_backup_20260831/` prefix also exists.

### Tables

| Table | Type | Rows | Load | Relevance to disputes |
| --- | --- | --- | --- | --- |
| customers | dimension | 150,000 | monthly snapshot | Identity, segment, country for authorization and fairness slices |
| products | dimension | 400,000 | monthly snapshot | Cards and accounts, `product_status` for preventive blocks |
| branches | dimension | 350 | full snapshot | Low |
| service_agents | dimension | 1,200 | monthly snapshot | Low |
| marketing_campaigns | dimension | 200 | full snapshot | None |
| transactions | fact | 5,000,000 | daily | The disputed charges: status, merchant, `is_fraud`, `fraud_score` |
| call_center_interactions | fact | 800,000 | daily | Contact reasons, FCR, follow-ups (workflow justification) |
| call_transcripts | fact | 200,000 | daily | Spanish call text (templated, weak) |
| satisfaction_surveys | fact | 250,000 | daily | CSAT, NPS, CES |
| digital_events | fact | 10,000,000 | daily | Low |
| complaints | fact | 80,000 | daily | Dispute cases: category, claimed amount, status, SLA |
| campaign_sends | fact | 2,000,000 | daily | None |
| daily_exchange_rates | reference | 3,000 | daily | Currency normalization |

Full column dictionary and FK graph: Notion "Data y data dictionary" page. Key FKs:
`customers.customer_id` is referenced by nearly every fact table; `products.product_id` by
transactions, digital_events and complaints; `call_center_interactions.interaction_id` by
call_transcripts, satisfaction_surveys and complaints.

### Intentional quality traps

- About 2% duplicates across tables (documented). **Unresolved:** ID-level and business-key dedup
  both find 0 in June 2026 transactions and 2026 complaints. Next steps: brief section 4.
- About 5% nulls in non-mandatory fields.
- Late-arriving partitions. Observed row counts are below documented totals (686k vs 800k
  interactions, 67k vs 80k complaints). June 2026 holds 0 transactions processed more than 3 days
  late; the unexplored `data_backup_20260831/` prefix may hold them.
- Schema evolution across partitions. Value drift already seen: see "Verified findings" below.
- A small share of orphaned foreign keys on purpose.

### Profiling findings (2025-03 sample for transactions and transcripts; full load for interactions and complaints)

Contact reasons over 686,296 interactions:

| Reason | Volume | FCR | Needs follow-up | Avg minutes |
| --- | --- | --- | --- | --- |
| Transaccional | 35.0% | 91.5% | 22% | 3.7 |
| Producto | 22.0% | 89.6% | 24% | 4.4 |
| Queja | 17.1% | 43.6% | 63% | 7.2 |
| Tecnico | 15.0% | 69.9% | 41% | 6.0 |
| Comercial | 8.0% | 65.2% | 45% | 9.0 |
| Retencion | 3.0% | 60.2% | 49% | 8.0 |

`contact_reason` equals `reason_category` (coarse). Escalation is a flat 10% across reasons.

Complaints (67,095): subcategories Cargo no reconocido 18.3%, Cobro indebido 18.2%, Problema con
app 18.1%, Atencion en sucursal 17.7%, Calidad de servicio 17.7%, null about 10%. Reception channel
is mostly Call Center (33,761), then Email, Web, App, Branch, Regulator.

### Do NOT train on or present as signal

- `complaints.description`: one template per category.
- `complaints.sla_breached` (about 20%), `compensation_granted` (about 7%) and
  `resolution_satisfaction` (about 3.0): flat across categories.
- `complaints.resolution`: 5 template strings, about 77% null.
- `call_transcripts.detected_intents`: almost always `consulta_general`. Texts contain unfilled
  placeholders such as `{monto}` and `{moneda}`.

### Usable signal

- `transactions.is_fraud` about 0.09% in the sample. **`fraud_score` leaks the label:** every
  non-fraud row scores <= 30.0, so a score above 30 means fraud with 100% precision. Keep it out of
  every model and out of the baseline; present it as a data-quality finding.
- Transaction status in the sample: Approved about 92%, Declined 5%, Pending 2%, Reversed 1%.

Implications: the dataset's intent labels are unusable, so any intent classifier needs a
team-labeled ES/PT utterance set with inter-annotator agreement on a sample. Portuguese test cases
are team-generated and must be labeled as such.

### Verified findings (profile of 2026-09-26: June 2026 transactions, 2026 complaints)

Each finding changes a design choice. Re-check against the full load before quoting it as final.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| Event time shifted | `transaction_date` hours 00-05 fall on the day after their `process_date` partition (25% of rows); 227 sampled rows land on 2026-06-18, after "today" | Derive the local date before window, velocity or time-of-day logic; confirm UTC on a raw CSV |
| No MXN in transactions or products | Mexican customers transact in USD; `amount_usd` is NULL whenever `currency = 'USD'` | Caps and features work in USD; MXN appears only in `complaints.claimed_amount` |
| Amounts are high | Median about $470; 14.8% <= $150, 38.6% $150-$500, 46.6% > $500 | The $500 ceiling caps containment near 53%; justify the threshold in the report |
| Merchant rarely known | `merchant_name` NULL in 77% of rows; names are generic ("Super Ahorro", "Cine Premium") | Charge matching leans on amount and date; merchant is a weak hint |
| Some rows cannot be disputed | Deposit and Adjustment rows are 17%; Declined, Pending and Reversed statuses about 8% | The policy needs the disputable-charge rule (brief clause `POL-DISP-TYPE`) |
| Complaint product link is unreliable | 82% of non-null `complaints.affected_product_id` point outside the complainant's own products | Never infer the complained product from that column |
| Name and enum drift | `transaction_country` holds "México" and "Mexico"; `product_type` values are Spanish ("Tarjeta Crédito") while the dictionary lists English; complaint `status` has no `INTAKE_RECEIVED`, `category` has no `Fraud`, `reception_channel` has no `Chat` | Normalize names; write only dictionary values |
| Repeat flag exists natively | `complaints.is_repeat_complainer` is true on 15% of complaints | Use or reconcile it instead of hardcoding false |
| Claim currency often missing | `complaints.currency` NULL on 68% of rows | Claimed amounts need a currency rule before any sum |
| S3 layout | Dimensions are flat CSVs under `data/`; facts are partitioned `year=/month=/day=`; a second root `data_backup_20260831/` exists | There is no `data/complaints.csv` |

## 8. Target architecture

Core design idea: **the model proposes, deterministic policy disposes.** The Understand stage only
interprets language and fills a strict JSON schema. A deterministic state machine, policy engine and
tool gateway decide and act. `customer_id` always comes from the session token, never from the model.
Dataset rows stay out of any external model call: Understand sees only the masked customer message.

| Stage / component | Responsibility | Tech (decided or proposed, see section 10) |
| --- | --- | --- |
| Identity + input guard | Mock OIDC/JWT test sessions with expiry; PII redaction; prompt-injection filter; language detection | FastAPI, JWT |
| Understand | Extract `{intent, transaction_ref, amount_hint, date_hint, reason, language, missing_fields}` into a Pydantic schema | Deterministic ES/PT keyword and slot extractor now; an LLM with structured output plugs in behind the same interface later |
| Decide | Synthetic dispute policy (brief v2.1 clause order) plus ML risk score | Policy-as-code, LightGBM |
| Act | Tool gateway: per-state tool allowlist, idempotency keys, bounded retries | FastAPI tool layer writing to the SQLite ops store |
| Verify | Read the created case or card status back from the system of record before telling the customer | SQLite ops store (`data/ops.sqlite`) |
| Escalate | Handoff packet: request, verified facts, actions taken, evidence, policy clauses, open questions | JSON plus Streamlit agent console |
| Policy explanations | Bilingual dispute policy with clause citations | Policy-as-code with clause ids (built); RAG only if time remains |
| Data platform | Bronze raw CSVs -> silver validated and deduplicated -> gold dispute and contact-reason marts | DuckDB (read-only for the app), Pandera or SQL checks |
| Observability | Traces, append-only audit log, experiment tracking, eval runs | Audit log in the ops store, MLflow; OpenTelemetry if time remains |

Learned components, each measured against a baseline:

1. **Unrecognized-charge risk model** on `transactions.is_fraud`, all years, time-based split,
   rules-only baseline vs gradient boosting, `fraud_score` excluded from both, threshold chosen by
   the cost of a missed escalation. This is the required ML deliverable.
2. **Intent and slot classifier** on a small team-labeled ES/PT set: keyword extractor vs
   multilingual embeddings plus logistic regression vs LLM zero-shot. Stretch goal.

## 9. Current state of the codebase and the gap

The repo holds the "OmniGuard AI" starter pipeline (the proposed measured baseline, wired to the
API) and a dispute stack beside it that nothing calls yet. `CLAUDE.md` describes how each is wired;
this table tracks the gap to the plan. 24 tests pass.

| Area | What exists | Gap vs plan |
| --- | --- | --- |
| Baseline pipeline | Single-shot orchestrator, English keyword rules, hand-tuned "ML" sigmoid, always-succeeding mock tools, in-memory HITL queue | Keep as the measured baseline. Fix the crash at `src/agents/orchestrator.py:130` (`and`/`or` precedence). Its card lock on "cargo no reconocido" and its refund promise count as unsafe outcomes in the report |
| Identity | `src/auth/session.py` HS256 JWT | No endpoint uses it; `JWT_SECRET` falls back to a hardcoded default |
| Dispute policy | `src/rules/dispute_policy.py`, brief v2.0 clause order | Brief v2.1 clauses (session, clarify, disputable charge, distress); legal before window; provisional credit as a candidate flag; the "hace -1 días" message on future-dated charges |
| Tool gateway | `src/tools/gateway.py` act-and-verify on DuckDB `silver_*`, fixture tests | Writes to the SQLite ops store, dictionary enums, card type and status guards, idempotency keys, audit log, escaped untrusted tags |
| Handoff packet | `src/domain/handoff.py` model | `customer_request`, `supporting_evidence`, `provisional_credit_recommendation`; nothing produces a packet yet |
| Data pipeline | `src/data/ingestion.py` bronze/silver/gold, customer-aligned sample with 0 orphans | Contracts, local event time, FX by transaction date, dedup, late arrivals, full-history load for ML |
| ML | Hand-tuned heuristic | LightGBM on all years without `fraud_score` |
| Understand | Baseline English keyword matching | ES/PT keyword and slot extractor behind the Understand interface |
| Orchestrator | None for disputes | Multi-turn five-stage state machine behind FastAPI and `get_current_session` |
| PII masker | Regex for cards, emails, US phones, SSN | LATAM documents (CURP, DNI, CC, CPF); stop masking amounts (a 7-digit COP amount becomes `[REDACTED_PHONE]`) |
| UI, eval harness, deployment | None | Streamlit chat and console; 250-case suite; public URL |
| Analysis notebook | `notebooks/01_problema_y_datos.ipynb` | Ran on the pre-fix lakehouse; rerun it and correct its false claim that most transactions fall under $150 (14.8% do) |
| README | Starter-kit text with a "7 pillars" rubric that is not the hackathon rubric | Rewrite to match the submission |
| `data/synthetic_samples.json` | 4 English scenarios in USD | Team-generated; replace with the ES/PT held-out suite |

## 10. Plan, lanes and open decisions

### Revised plan (2026-09-26)

Revised after the day-2 audit: days 1-2 left contracts, wiring and data correctness unfinished.
The order builds one working end-to-end slice first, then widens it. A day is done only when its
"done when" holds.

| Day | Date | Focus | Done when |
| --- | --- | --- | --- |
| 2 | Sep 26 | Audit, brief v2.1, this plan; commit the untracked dispute stack on a branch; confirm the event-time shift on a raw CSV | The team confirms or changes every "Proposed" row below |
| 3 | Sep 27 | Data: contracts, local event time, FX by transaction date, dedup and backup-prefix probe (2 h cap). Backend: SQLite ops store and audit log, gateway guards and enums, policy v2.1 clauses | Every fix has a test that failed first; ingestion reruns with contract checks green |
| 4 | Sep 28 | Five-stage multi-turn orchestrator behind FastAPI and `get_current_session`; charge matching and clarification; handoff producer | One Spanish dispute conversation runs end to end through the API and ends in a verified case |
| 5 | Sep 29 | ML on all years, time split, LightGBM vs heuristic baseline, cost-based threshold, MLflow; wire `ml_risk_score` and the 48h count; input guard for LATAM PII and escaped tags | The model beats the baseline on the held-out time window, and the run is logged |
| 6 | Sep 30 | Streamlit customer chat (ES/PT) and HITL console; eval harness with the first 60 cases | The three case types run in the UI in both languages |
| 7 | Oct 1 | Full 250-case suite with provenance labels; baseline vs proposed, 3 repeats, slices | A metrics report covers every brief section 5 metric with denominators |
| 8 | Oct 2 | Fix failures; bounded retries, safe fallback, tracing; deploy | A public URL serves the demo |
| 9 | Oct 3 | README rewrite, architecture, metrics, limitations, route to production; rerun the notebook | Every doc claim matches the code and the data |
| 10 | Oct 4-5 | 4-6 slides, 3-minute video, repo rename, submission email | Submission sent to `hackathon.admin@factored.ai` |

Cut order when late: the intent classifier, then MLflow (a JSON run log instead), then Portuguese
policy text. Always kept: the end-to-end flow, act-and-verify, the handoff packet, the held-out
comparison with the baseline, the deployment and the video.

Lanes, one owner each: agent and backend; ML and evaluation; data engineering; analytics and docs.

### Decision log

Ask the team before acting on a "Proposed" or "Open" row. Record each closure here with its date.

| Decision | Status | Resolution or proposal |
| --- | --- | --- |
| Operational system of record | Decided 2026-09-26 | SQLite `data/ops.sqlite` for cases, card locks, sessions and the audit log; DuckDB read-only for the app |
| Understand stage | Decided 2026-09-26 | Deterministic ES/PT keyword and slot extractor now; an LLM provider later behind the same interface |
| Git workflow | Decided 2026-09-26 | Work on branches, commit per phase with the suite green |
| `fraud_score` leakage | Settled by data 2026-09-26 | Leaks the label; excluded from the model and the baseline |
| Workflow | Proposed | Transaction-dispute intake (Notion "Task" still says pending; fallback: credit eligibility) |
| Provisional credit | Proposed | Candidate flag for a human only (brief v2.1, rule 8); the code still returns it as an autonomous outcome |
| Dispute policy | Proposed | Brief v2.1 clauses and order |
| $500 escalation ceiling | Proposed | Keep it and report the ~53% containment ceiling it implies |
| Baseline | Proposed | The current starter pipeline, measured on the same held-out suite |
| Rebuild vs evolve | Proposed | Evolve: keep layout and contracts, build the dispute stack beside the baseline |
| Policy explanations | Proposed | Policy-as-code with clause ids; RAG only if time remains |
| Learned components | Proposed | Fraud model required; intent classifier stretch |
| Portuguese depth | Proposed | PT utterances and answers only, labeled team-generated |
| UI and deployment | Proposed | Streamlit; Docker on Render or Fly.io with a public URL |
| Team size and lane owners | Open | |
| Preventive card lock confirmation | Open | Whether the customer must confirm before the lock |
| Disputable-charge rule and distress keywords | Open | Brief clauses `POL-DISP-TYPE` and `POL-ESC-DISTRESS` |
| Documentation language | Open | |

## 11. Working conventions for agents

- **Environment:** Python 3.11+, `uv`. Install with `uv sync`, test with `uv run pytest -v`, run
  the API with `uv run uvicorn src.api.app:app --reload --port 8000`.
- **Secrets:** `.env` is a git-ignored file holding the read-only AWS keys and any API keys; keep it
  out of commits, logs and prompts. Prompts sent to an external model carry only the masked customer
  message, never keys or dataset rows.
- **Git:** work on a branch and commit per phase with the suite green (decision log, section 10).
- **Data provenance:** every dataset, fixture and eval case carries a label: `synthetic-organizer`,
  `team-generated`, or `derived`. Portuguese content is always `team-generated`.
- **Authorization:** any tool that reads or writes customer data takes `customer_id` from the
  validated session, never from a model output or request body.
- **Verification:** a tool call is not "done" until a read-back from the store confirms the new
  state. Report unverified actions as pending, never as complete.
- **Explanations:** cite policy clause ids and execution records. Never expose or log model
  reasoning as an audit artifact.
- **Tests:** keep the suite green. New behavior in the orchestrator, policy engine or tool gateway
  ships with tests, including the failure cases listed in section 5.
- **Languages:** customer-facing text in the customer's detected language (ES or PT). Code,
  identifiers and commit messages in English.
- **Writing style for any document a human will read:** no em-dashes or en-dashes. Use commas,
  periods, parentheses or colons.
- **Scope discipline:** one workflow. If a change adds a second workflow, stop and ask.

## 12. Factored support team (mentors)

Paul Leon (Data Engineer), Antonio Gonzalez Dumar (Analytics Engineer), Brandon Rodriguez (Data
Analyst), Cindy Lobo (Technical Recruiter), Juan Jaramillo (Sr. Director Solutions Engineering),
Diego Ralon (ML Engineer), Luis Bertozzo (ML Engineer), Diego Medina (Marketing Manager).

Final takeaway from the organizers: build something that works, prove it works, know when it should
not act, and show what it would take to make it real. *AI should not be autonomous just because it can be.*
