# AlterEgo: transaction-dispute intake for LATAM Bank

Team AlterEgo's submission to the **Factored AI & Data Hackathon 2026**: an AI-first customer-service system for one workflow, **transaction-dispute intake**, in Spanish and Portuguese. The agent finds the charge the customer does not recognize, checks it against a written dispute policy, opens a case and confirms it only after reading it back, protects the customer with a card lock they confirm, and hands off to a human with a structured packet when the case needs one. It never moves money.

> **Status (2026-10-04, day 10 of 10).** The dispute stack runs end to end behind the API and the React chat and console, with Supabase sign-in. It is deployed on Vercel at <https://alterego-silk.vercel.app>, over one Supabase project that is also production. This README separates what is delivered from what was planned and not delivered, and states the results and the limitations.

## How it works

The model proposes; deterministic code disposes. Every interaction runs **Understand -> Decide -> Act -> Verify -> Escalate**. The table describes the code as delivered.

| Stage | What it does | Delivered |
| --- | --- | --- |
| Identity and guards | The customer signs in; the API verifies the session token and takes `customer_id` only from it; PII is masked before any model call | Supabase Auth (ES256 tokens verified against the project JWKS) and FastAPI; a local test issuer exists only in development and test |
| Understand | Reads the masked message: intent, stolen card, distress, amount, date, merchant | An ES/PT keyword and regex extractor; Jev (TypeSafe AI) typed signals when a key is configured and the daily budget allows |
| Decide | Applies the dispute policy clause by clause, plus a fraud-risk score | Policy as code v2.3 (clause ids such as `POL-WIN-60`, `POL-ESC-500`); a risk model transferred from the IEEE-CIS competition (scikit-learn gradient boosting), active only when its model file is installed |
| Act and Verify | Opens the case or locks the card, then reads the record back before telling the customer | Tool gateway on DuckDB or Supabase Postgres (`ops` schema): ownership check before the write (and, for the card lock, an active card only), read-back after it, append-only audit log |
| Escalate | Sends legal, high-value, high-risk, multi-charge, distress and still-ambiguous cases to a human | Structured handoff packet and an English review console |
| Converse and explain | Replies in Spanish or Portuguese from verified facts; explains the policy with the clause cited | Templated replies; a policy explainer that retrieves clauses with BM25 and never changes a decision |

**Planned and not delivered** (decisions in [`docs/PLAN.md`](docs/PLAN.md)):

- Replies written by Claude Haiku with placeholders filled by code. The router records which engine it would choose, but no Claude call exists: every reply is a template.
- Local multilingual embeddings (E5) for the policy explainer. They are measured offline only (`--e5`) and do not fit the Vercel bundle, so BM25 serves.
- LightGBM served through ONNX. The model is scikit-learn's gradient boosting, kept with joblib (TQ-022).
- Idempotency keys, the audit row in the same transaction as the write, and bounded retries before the outage handoff (brief section 3.3). A duplicate case is prevented by a read before the write, not by a database constraint.
- Card unlock as a console action: the policy's authentication matrix declares it, and it is not built.
- The team's adjudicated labels for the held-out suite and Cohen's kappa (TQ-018): the suite carries design labels.

The component diagram in [`docs/PLAN.md`](docs/PLAN.md) ("Arquitectura del sistema") shows the target, not the delivery. Deployment target: Vercel for the API and the React front, Supabase for identity and the operational database, both on free plans.

## What runs today

- **Reference baseline** (the starter pipeline, wired to the API): `/health`, plus `/api/v1/sanitize`, `/api/v1/triage`, `/api/v1/hitl/queue` and `/api/v1/hitl/resolve`, which answer only when `APP_ENV` is development or test. English keyword rules and mock tools. It is measured as is in the evaluation and is not deployed.
- **Dispute stack** (wired since 27 Sep, behind the session token): the policy engine v2.3 (`src/rules/dispute_policy.py`, spec `docs/specs/dispute-policy-v2.3.md`), the Understand router (`src/understand/`: Jev typed signals when a key and the daily budget allow, the ES/PT keyword extractor otherwise), the five-stage orchestrator (`src/orchestrator/`), a policy explainer (`src/rag/`: BM25 over the 13 policy clauses, templated answers with the clause cited) that is on since 2-Oct with a BM25 gate calibrated on the policy question bank (it misses many paraphrased questions; see `reports/rag_benchmark.md`), the operational store on DuckDB or Postgres (`src/ops/`, DDL in `supabase/migrations/0001_ops.sql`), the act-and-verify gateway over the lakehouse or the Postgres serving copy (`src/tools/`), and the API: customer chat at `/api/v1/disputes/...`, the English HITL console at `/api/v1/console/...` (agent role), a local test issuer at `/api/v1/auth/personas` and `/api/v1/auth/test-session` (development and test only), and `/api/v1/auth/me`, which returns the verified identity. Swagger lists them.
- **Data pipeline**: S3 CSVs into a local DuckDB lakehouse (bronze, silver, gold) over a customer-aligned sample of 25,000 customers (`src/data/ingestion.py`), plus the full 2023 to 2026 history in a separate file for the ML work.
- **Evaluation harness** (`src/eval/`): scripted cases in JSONL (`data/eval/dev_cases.jsonl`, 19 team-generated development cases in ES and PT), runners for our architecture in rules-only mode and the reference baseline (the starter pipeline through an adapter), the brief's metrics as counts over denominators with slices by language, segment and country, and a Markdown report (`reports/eval_dev.md`).
- **Risk model** (`src/ml/fraud_risk_transfer.py`): the bank's fraud label showed no learnable signal in our experiments, so the served score is trained on the IEEE-CIS competition over the deployable contract features (spec `docs/specs/fraud-risk-model-v1-ieee-cis.md`), with the escalation threshold at percentile 98 of the bank's Web and App window. `TransferRiskScorer` (`src/ml/transfer_scorer.py`) feeds `POL-ESC-ML-RISK` and the handoff's risk explanation when `models/fraud_risk_ieee.joblib` exists, and every training run is logged to MLflow. The earlier leak-free pipeline on bank features (`src/ml/fraud_risk.py`) stays as the evidence: on the full history its test ROC AUC is 0.497.
- **Analysis notebooks**: [`notebooks/01_problema_y_datos.ipynb`](notebooks/01_problema_y_datos.ipynb), the data behind the workflow choice; [`notebooks/02_risk_model_experiment.ipynb`](notebooks/02_risk_model_experiment.ipynb), why our models could not learn the fraud label without the leak; [`notebooks/03_fraud_signal_search.ipynb`](notebooks/03_fraud_signal_search.ipynb), the search for a fraud signal across every other table (needs `data/lakehouse_aux.duckdb` from `scripts/data_ops/load_aux_tables.py`). Run a notebook with `uv run python scripts/notebooks/run_notebook.py <path>`.
- **Tests**: CI runs the suite on every PR against a Postgres service. The 6 in `tests/test_data_integrity.py` need a local `data/lakehouse.duckdb` and skip without it; the Postgres tests (`tests/test_ops_store.py`, `tests/test_gateway_postgres.py`, `tests/test_publish_serving.py`) run only with `TEST_DATABASE_URL` set.

## Quick start

Prerequisites: Python 3.12 (`.python-version`, as in CI, the Docker images and Vercel) and [`uv`](https://github.com/astral-sh/uv), or only Docker: `docker compose run --rm dev <command>` runs any Python command below in a Linux container, the same on Mac and Windows. Building the lakehouse needs the read-only AWS keys from the data dictionary in a git-ignored `.env`; never commit them.

```bash
uv sync                                               # install from the lockfile
uv run pytest -v                                      # test suite
docker compose run --rm dev                           # test suite as CI runs it (Linux, Python 3.12, Postgres 17), no local Python needed
docker compose build dev                              # rebuild the dev image after a pull that changes uv.lock (it changed with #23 and #24)
uv run uvicorn src.api.app:app --reload --port 8000   # API, Swagger at http://localhost:8000/docs; serves frontend/dist when built
docker compose run --rm -p 8000:8000 dev uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000   # the same API from the dev container
uv run python main.py                                 # baseline demo over data/synthetic_samples.json
uv run python -m src.data.ingestion                   # build data/lakehouse.duckdb from S3
docker-compose up --build -d                          # API plus the React build in one image (mount ./data with the lakehouse)
uv run python -m src.data.publish_serving --database-url postgresql://... --source data/lakehouse.duckdb   # publish the minimized bank subset to Postgres
cd frontend && npm install && npm run dev            # React chat and console on http://localhost:5173, proxied to the API (see frontend/README.md)
uv run python -m src.eval.run data/eval/dev_cases.jsonl --out reports/eval_dev --repeats 3   # evaluation: baseline vs proposed, report in reports/
uv run python -m src.ml.fraud_risk_transfer --competition data/kaggle --lakehouse data/lakehouse_full.duckdb --out reports/ml --model models/fraud_risk_ieee.joblib   # train the served risk model (IEEE-CIS files in data/kaggle)
```

Run commands from the repo root: `data/lakehouse.duckdb` is a relative path. The dispute API needs the lakehouse for bank facts; the operational store (`data/ops.duckdb`, or `OPS_DB_PATH=postgresql://...`) is created on first use. Try it: `GET /api/v1/auth/personas`, `POST /api/v1/auth/test-session`, then chat at `POST /api/v1/disputes/conversations` and `.../messages` with the bearer token. The front signs in with Supabase Auth (email and password; personas from `src.auth.seed_personas`) when built with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend/.env.local`; without them it shows the local persona picker. The local issuer needs `APP_ENV` development or test: unset, it means production.

## Data

LATAM Bank Dataset v1.0.0 from the organizers: 100% synthetic, about 19 million rows in 13 tables, Mexico, Colombia and Argentina, all text in Spanish. There is no Portuguese in the data, so every Portuguese case is team-generated and labeled as such. Findings that shape the design, such as `fraud_score` leaking the fraud label and transaction timestamps offset from the processing day, are in [`AGENTS.md`](AGENTS.md) section 7.

## Results

Every suite runs through `src/eval/` as scripted conversations, offline and in process: these are not production measurements. Every rate carries its numerator and denominator.

**What the runs compare.** The reference baseline is the starter pipeline the repository began with, measured as is through an adapter (only its crash fixed), so its card lock on an unrecognized charge and its refund promise count as unsafe. The other system is our architecture in rules-only mode: keyword extractor and policy as code, with no risk model, no Jev, no LLM and no policy explainer. The brief names this rules-only stack our main baseline. The runs therefore show what the architecture and the policy deliver; they attribute nothing to the learned components, which no committed end-to-end run measures yet.

**Metric definitions** (`src/eval/metrics.py`). Safe automated resolution: the cases whose label expects an autonomous resolution and that end correctly with no human, over those cases (107 of the 250 held-out cases), and the same successes over every in-scope case, meaning every dispute conversation that is neither an out-of-scope request nor an API attack (230 of the 250; TQ-034). On the held-out suite 123 of those 230 need a human, an abstention or a clarification by design, so 107 of 230 (46.5 %) is the ceiling of the in-scope rate. Unsafe outcomes: the cases with at least one unsafe result (unauthorized access or disclosure, a case opened or a card locked that the label forbids, an action not verified, a false confirmation, a promise of money, a crash, or a materially incorrect outcome, which includes an abstention or a clarification on a case that needed a human when no human was reached, TQ-035), over all cases; the reasons are counted apart, so no case counts twice. Cost: rules-only mode spends no model tokens, and compute is not measured.

### Held-out suite: 250 conversations, frozen on 30 Sep

150 Spanish and 100 Portuguese conversations: 63 derived from unchanged rows of the dataset and 187 team-generated (every Portuguese case and every fabricated or altered fact). The labels are design labels written from the spec; the team did not double-label the suite, so there are no adjudicated labels and no kappa (TQ-018).

First run, before any fix (30 Sep, 3 identical repeats, recorded in PR #12), re-scored on 3 Oct with the definitions above ([`reports/eval_heldout_blind.md`](reports/eval_heldout_blind.md): the outcomes of that run's own code, commit `011e931`, judged by the current judge). Under the earlier judge its unsafe outcomes were 12.4 % (31 of 250); TQ-035 adds 8:

| Metric | Reference baseline | Our architecture, rules-only |
| --- | --- | --- |
| Safe automated resolution | 3.7 % (4 of 107) | 63.6 % (68 of 107) |
| Safe automated resolution over in-scope cases | 1.7 % (4 of 230) | 29.6 % (68 of 230) |
| Containment | 44.0 % (110 of 250) | 76.4 % (191 of 250) |
| Escalation precision | 48.6 % (68 of 140) | 96.6 % (57 of 59) |
| Escalation recall | 69.4 % (68 of 98) | 58.2 % (57 of 98) |
| Unsafe outcomes | 48.8 % (122 of 250) | 15.6 % (39 of 250) |
| Crashes | 0 | 9 |

That run found seven problems. The six in the code were fixed the same day, each with a test of its own, and the suite was not edited. Every later run reuses the cases that drove those fixes, so it is a measurement after error analysis, not a second blind evaluation.

Rerun on `main` at `9efb497` on 4 Oct (3 repeats, the same safe automated resolution rate in every repeat), after those fixes and the later ones, with the TQ-034 and TQ-035 scoring, which adds no unsafe outcome here ([`reports/eval_heldout.md`](reports/eval_heldout.md)). The reruns of 3 Oct, at `e52a5ec` and `cfe5ab4`, gave the same safety figures:

| Metric | Reference baseline | Our architecture, rules-only |
| --- | --- | --- |
| Safe automated resolution | 3.7 % (4 of 107) | 98.1 % (105 of 107) |
| Safe automated resolution over in-scope cases | 1.7 % (4 of 230) | 45.7 % (105 of 230) |
| Containment | 44.0 % (110 of 250) | 68.8 % (172 of 250) |
| Escalation precision | 48.6 % (68 of 140) | 100.0 % (78 of 78) |
| Escalation recall | 69.4 % (68 of 98) | 79.6 % (78 of 98) |
| Unsafe outcomes | 48.8 % (122 of 250) | 8.0 % (20 of 250) |
| Exact outcome accuracy | 52.4 % (131 of 250) | 88.4 % (221 of 250) |
| Crashes | 0 | 0 |

The 20 unsafe outcomes left are the 20 high-risk foreign online purchases of the suite: with no risk model in the run, the system opens a case where the label expects a human, and the same 20 cases are the missed transfers. By language: Spanish 59 of 61 safe resolutions and 12 of 150 unsafe outcomes, Portuguese 46 of 46 and 8 of 100. Latency p50 / p95 was 161.6 / 662.1 ms, in process, with no network, in the dev container on a Windows laptop; it depends on the machine (the report of 3 Oct read 25.0 / 85.1 ms on another one). Reproduce it with `uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout --repeats 3`. Both held-out reports are committed next to the development one (TQ-019).

Exact outcomes fell from 227 to 221 with PR #39 (3 Oct), which stopped the card lock from landing on one of several active cards when the charge that decides the turn is on none of them. Six cases changed: HO-126, HO-130, HO-148, HO-152, HO-160 and HO-215. Their design labels expect a lock (offered, in HO-215) on the card the old code picked, the first active one. The system now hands the choice to a specialist, and the scripted "Sí" that follows reaches an escalated conversation and gets a clarification. The six stay escalated, and the safe resolution and unsafe counts do not change. The frozen suite was not edited: human labels were the place to correct such expectations, and the team did not produce them (TQ-018).

### Development split: 19 cases

Team-generated cases used while building the system, so they show that it handles the cases it was built for, not that it generalizes. Reference baseline: 0 of 9 safe automated resolutions and 11 of 19 unsafe outcomes. Our architecture in rules-only mode: 9 of 9 and 0 of 19, and 9 of the 18 in-scope cases ([`reports/eval_dev.md`](reports/eval_dev.md), 3 repeats; CI reruns the split on every pull request).

### Policy explainer

Measured on the test split of the policy question bank, which an LLM drafted and the team accepted with its deviations declared: 36.7 % of its actions are right, it abstains on 61.1 % of the answerable questions, and 27.3 % of its answers cite a wrong clause ([`reports/rag_benchmark.md`](reports/rag_benchmark.md)). BM25 misses paraphrased questions. The explainer never decides an outcome and never takes a turn that names a charge or fires a legal or distress escalation, but a wrong citation can mislead the customer. The team kept it on for the demo with these limits; removing `data/rag_gate.json` turns it off.

### Risk model

A leak-free gradient boosting on the bank's own features scores a test ROC AUC of 0.497 on the full 2023 to 2026 history ([`reports/ml_full/`](reports/ml_full/)): our experiments found no learnable signal in the bank's fraud label, and `fraud_score` is excluded everywhere because it leaks that label. The served score is transferred from the IEEE-CIS competition: ROC AUC 0.817 and PR AUC 0.165 on the competition's own test split ([`reports/ml/fraud_risk_transfer.md`](reports/ml/fraud_risk_transfer.md)). Those numbers measure the source domain. No bank label can validate the transfer, so the score routes charges to a human; it is not a fraud detector validated on LATAM Bank. The model file is not in the repository, and without it `POL-ESC-ML-RISK` never fires, which is the state of every run above; the handoff packet then tells the agent that the risk was not scored, never a score of zero.

## Limitations

- **Languages.** The dataset holds no Portuguese, so every Portuguese case is team-generated. Slices by language, country and segment are small samples.
- **Labels.** The held-out suite carries design labels written from the spec. The team did not double-label it, so there is no Cohen's kappa and no adjudicated label set (TQ-018).
- **What was measured.** The headline results are the rules-only configuration. Since 5-Oct the same suite also ran with the risk model (`reports/eval_heldout_model.md`: 101 of 107 safe resolutions, 9 of 250 unsafe), with the policy explainer on (`reports/eval_heldout_explainer.md`: the same outcome in all 250 cases, since none asks a policy question) and with Jev (`reports/jev_evaluation_report.md`: the same 105 of 107, and 26 of 250 unsafe against 20). `docs/crisp-dm/09-plan-de-pendientes.md` lists what is still open.
- **Held-out reuse.** Numbers after the first run come from the same cases that drove the fixes.
- **Risk model.** The transfer from IEEE-CIS is not validated on bank data, and without the model file no charge escalates for risk. We use external data because the bank's own fraud label showed no learnable signal (test ROC AUC 0.497), so a model trained on it would route charges at random. The IEEE-CIS data is external: real e-commerce transactions, de-identified, from a public Kaggle competition, under the competition's rules (competition and non-commercial use); the team recorded the mentors' approval of this data use (TQ-032, confirmed on 5-Oct). The repository holds the trained model, never the competition files.
- **Deployed configuration.** Production runs the rules-only stack plus the policy explainer, and no Jev or LLM key is configured, so every reply is a template. The risk-model file is tracked in git since 5-Oct; production serves the score only from the first deployment that includes it, and until then `POL-ESC-ML-RISK` never fires there. The explainer (BM25) is on there, and the end-to-end runs above leave it out; its own measurements are in the policy explainer section.
- **Card lock.** In production the lock is written to the operational schema (`ops.card_locks`) and verified by reading it back there; no bank system receives it.
- **Tracing.** There is no distributed tracing; OpenTelemetry was planned and dropped on 4 Oct (TQ-036). The append-only audit log is the execution record of each turn.
- **Write path.** There are no idempotency keys, the audit row is written apart from the action, and there are no bounded retries. Concurrent requests are not tested.
- **Deployment and capacity.** The public URL (<https://alterego-silk.vercel.app>) runs on Vercel Hobby and one Supabase Free project that is also production: there is no separate demo project, the Free plan pauses an idle project, and the canary planned to keep it awake was not built; locally, DuckDB allows one writer process. No load test has been run.
- **Business date.** Window and account-age math use 2026-06-17, the end date of the dataset, not the wall clock.

## Documentation

| Document | Language | What it holds |
| --- | --- | --- |
| [`AGENTS.md`](AGENTS.md) | English | Hackathon rules, judging, verified data findings, target architecture, gap between code and plan |
| [`CLAUDE.md`](CLAUDE.md) | English | How to run the code and how it is wired today |
| [`docs/PLAN.md`](docs/PLAN.md) | Spanish | Problem question, architecture, decision log, work fronts, day-by-day roadmap |
| [`docs/TEAM_BRIEF_COMPLEMENTED.md`](docs/TEAM_BRIEF_COMPLEMENTED.md) | English | Dispute policy spec, data contracts, handoff packet, evaluation suite and metric formulas |
| [`docs/SUPABASE_VERCEL.md`](docs/SUPABASE_VERCEL.md) | Spanish | Identity, database schemas, database security, deployment and their risks |
| [`docs/JEV_TYPESAFE_AI.md`](docs/JEV_TYPESAFE_AI.md) | Spanish | Jev integration design: typed signals and the policy clauses they feed |
| [`docs/SECURITY_AUDIT_PLAN.md`](docs/SECURITY_AUDIT_PLAN.md) | Spanish | Security findings SEC-01 to SEC-10 and acceptance criteria per gate |
| [`docs/specs/`](docs/specs/) | English | Specs of the dispute policy v2.3, the transferred risk model and the Supabase sign-in; a customer-profile risk explanation proposal (not decided, not built) |
| [`docs/reviews/`](docs/reviews/) | Spanish | Adversarial reviews of the plan, audits of the code and docs against real runs, and a reuse review of a starter repo |

## Ground rules

These come from the official problem statement; breaking one disqualifies the work.

- Identity comes from a verified session, never from a customer or document number alone.
- Permissions and policy live in code, never in prompts. The model proposes; code decides.
- Only actions verified by reading back from the system of record are reported as done.
- No real money movement or credit decisions: provisional credit is at most a flag a human reviews.
- No credentials or private records in the repo or in calls to external models.
- Limits are stated honestly: data, language coverage, capacity and deployment.
