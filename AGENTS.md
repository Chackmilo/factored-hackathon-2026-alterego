# AGENTS.md

Instructions and context for AI coding agents (and new teammates) working in this repository.
Read this file before touching code. It consolidates the team Notion workspace, the team brief,
the official hackathon rules and the current state of the codebase as of 2026-09-25.

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
| Claude Doc: Factored Hackathon 2026 Team Brief | The team's proposal: rationale, architecture, evaluation plan, 10-day plan, open decisions |
| Official Problem Statement (Google Doc) | https://docs.google.com/document/d/18AwONT8hQupRcfNPLFrPo6fHOJ_OUn1nBf-3jMnla2c/edit |
| LATAM Bank Dataset Summary (PDF) | https://drive.google.com/file/d/1V7n9v0zuv9SYzpW2AzPnssgAp5X_buXc/view |
| LATAM Bank Complete Data Dictionary (PDF) | [link to the organizer's data dictionary removed] |

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
| Normal | "No reconozco un cargo de ayer en Oxxo" | Find the transaction, check the dispute window, open the case, read it back, confirm |
| Ambiguous | "Tengo um cobranca estranha" with several candidate charges | List options and ask. Out of window: explain the policy and abstain |
| Human required | High amount, several unrecognized charges, or high fraud score | Preventive card block plus a handoff packet of verified facts |

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

- About 2% duplicates across tables. ID-level dedup found none, so duplicates likely require
  business-key matching. Still to verify.
- About 5% nulls in non-mandatory fields.
- Late-arriving partitions. Observed row counts are below documented totals (686k vs 800k
  interactions, 67k vs 80k complaints).
- Schema evolution across partitions.
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

- `transactions.is_fraud` about 0.09% in the sample. `fraud_score` averages about 50 on fraud vs
  about 15 otherwise. **Check whether `fraud_score` is derived from `is_fraud` before using it as a
  feature.** Treat this as a day-1 task.
- Transaction status in the sample: Approved about 92%, Declined 5%, Pending 2%, Reversed 1%.

Implications: the dataset's intent labels are unusable, so any intent classifier needs a
team-labeled ES/PT utterance set with inter-annotator agreement on a sample. Portuguese test cases
are team-generated and must be labeled as such.

## 8. Target architecture

Core design idea: **the LLM proposes, deterministic policy disposes.** The LLM only interprets
language and fills a strict JSON schema. A deterministic state machine, policy engine and tool
gateway decide and act. `customer_id` always comes from the session token, never from the model.

| Stage / component | Responsibility | Candidate tech |
| --- | --- | --- |
| Identity + input guard | Mock OIDC/JWT test sessions with expiry; PII redaction; prompt-injection filter; language detection | FastAPI, JWT |
| Understand | Extract `{intent, transaction_ref, reason, missing_fields}` into a Pydantic schema | LLM with structured output |
| Decide | Synthetic dispute policy (window, amount caps per currency, confirmation rules) plus fraud-risk score | Policy-as-code, scikit-learn or LightGBM |
| Act | Tool gateway: per-state tool allowlist, idempotency keys, bounded retries | FastAPI tool layer |
| Verify | Read the created case or card status back from the system of record before telling the customer | Postgres |
| Escalate | Handoff packet: request, verified facts, actions taken, evidence, policy clauses, open questions | JSON plus agent console |
| Policy explanations | Bilingual dispute policy with clause citations | Policy-as-code with clause ids, or pgvector RAG (under discussion) |
| Data platform | Bronze raw CSVs -> silver validated and deduplicated -> gold dispute and contact-reason marts | DuckDB/dbt or Databricks, Pandera |
| Observability | Traces, append-only audit log, experiment tracking, eval runs | Langfuse or OpenTelemetry, MLflow |

Learned components, each measured against a baseline:

1. **Unrecognized-charge risk model** on `transactions.is_fraud`, time-based split, rules-only
   baseline vs gradient boosting, threshold chosen by the cost of a missed escalation. This is the
   required ML deliverable.
2. **Intent and slot classifier** on a small team-labeled ES/PT set: keyword rules vs multilingual
   embeddings plus logistic regression vs LLM zero-shot. Stretch goal; the LLM already extracts
   intent.

## 9. Current state of the codebase and the gap

The repo is a starter kit named "OmniGuard AI" (see `README.md`, `src/`). It does **not** yet
implement the plan above. Know what is real and what is scaffolding:

| Area | What exists | Status vs plan |
| --- | --- | --- |
| Layout and contracts | `src/{domain,core,privacy,rules,ml,agents,hitl,api}`, Pydantic v2 schemas, `uv` lockfile, Dockerfile, docker-compose, 13 passing tests | Keep |
| PII masker | Regex redaction of cards, emails, phones, SSN | Keep, extend for LATAM document formats |
| Orchestrator | Single-shot, one request one decision, English keyword matching, simulated LLM call (`record_tokens(450, 120)`), USD only | Rewrite as multi-turn five-stage state machine |
| Rules engine | Regex keyword rules, sanctioned-country set, 10x-average anomaly rule | Replace with dispute policy-as-code with clause ids |
| "ML" fraud detector | Hand-tuned logistic sigmoid, no training, no data | Replace with a model trained on `transactions.is_fraud` |
| Tools | Hardcoded mocks that always succeed, auto "provisional credit" | Rewrite against Postgres system of record; remove provisional credit as an action |
| HITL queue | In-memory dict | Persist; produce the structured handoff packet |
| Identity | None | Add mock OIDC/JWT test sessions |
| LLM | `LLM_PROVIDER=mock`, keys for openai/anthropic/gemini/groq in config, nothing wired | Wire one provider behind a thin interface; keep mock for tests |
| Data pipeline | None | Build bronze/silver/gold with contracts and a late-arrival fixture |
| README | Spanish, describes a "7 pillars" rubric that is not the hackathon rubric | Rewrite to match the actual submission |
| `data/synthetic_samples.json` | 4 English scenarios in USD | Team-generated; replace with ES/PT held-out suite |

Proposal on the table: keep the current pipeline as the **measured baseline** (rules plus heuristic
score, no LLM) and build the proposed system next to it.

## 10. Plan, lanes and open decisions

### 10-day plan (from the team brief)

| Days | Dates | Focus |
| --- | --- | --- |
| 1-2 | Sep 25-26 | Schemas and contracts, bronze/silver/gold pipeline, core bank mock API, identity service |
| 3-4 | Sep 27-28 | Orchestrator state machine, tool gateway with permissions, policy engine, bilingual policy |
| 5-6 | Sep 29-30 | Intent classifier and fraud-risk model vs baselines in MLflow; input guard; handoff packet and agent console |
| 7 | Oct 1 | Held-out and red-team suite, first metrics run, fix what fails |
| 8 | Oct 2 | Frontend polish, analytics view, deployment |
| 9 | Oct 3 | Docs: rationale, architecture, metrics, limitations and remaining work |
| 10 | Oct 4-5 | Demo video, buffer, submission |

Suggested lanes, one owner each: agent and backend; ML and evaluation; data engineering;
analytics and docs.

### Open decisions (do not assume, ask the team)

- [ ] Confirm disputes as the workflow (fallback: credit eligibility). An unanswered comment on
      this sits in the team brief.
- [ ] Team size and owner per lane.
- [ ] Rebuild vs evolve the starter (proposal: keep layout and contracts, rewrite orchestrator,
      rules, ML scorer, tools, README).
- [ ] Use the current starter pipeline as the measured baseline.
- [ ] Portuguese depth: PT utterances and answers only, or also PT policy text, or a fake Brazil
      cohort (proposal: utterances and answers only, documented as team-generated).
- [ ] Exact action set and whether preventive block needs explicit customer confirmation.
- [ ] Learned components: fraud model required, intent classifier stretch.
- [ ] Policy RAG vs policy-as-code with clause citations.
- [ ] Stack: DuckDB/dbt vs Databricks; Postgres vs SQLite; which LLM provider.
- [ ] Where the profiled data lives and who holds the AWS keys.
- [ ] Multi-turn session state store and customer-facing surface (chat UI vs API only).
- [ ] Deployment target (docker-compose floor, public URL stretch) and documentation language.
- [ ] Check whether `fraud_score` leaks the `is_fraud` label.
- [ ] Define the synthetic dispute policy (window, caps per currency, confirmation rules).

## 11. Working conventions for agents

- **Environment:** Python 3.11+, `uv`. Install with `uv sync`, test with `uv run pytest -v`, run
  the API with `uv run uvicorn src.api.app:app --reload --port 8000`.
- **Secrets:** never commit `.env`. Never paste AWS keys, API keys or any dataset row into a prompt
  sent to an external model. The `.env/` directory currently in the repo root is a stray
  virtualenv, not a secrets file.
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
