# AlterEgo: transaction-dispute intake for LATAM Bank

Team AlterEgo's submission to the **Factored AI & Data Hackathon 2026**: an AI-first customer-service system for one workflow, **transaction-dispute intake**, in Spanish and Portuguese. The agent finds the charge the customer does not recognize, checks it against a written dispute policy, opens a case and confirms it only after reading it back, protects the customer with a card lock they confirm, and hands off to a human with a structured packet when the case needs one. It never moves money.

> **Status (2026-09-29, day 5 of 10).** The dispute stack runs end to end behind the API and the React chat and console; the deployment is not live yet. This README describes the plan and the code that runs today. The final README, with results, the deployment URL and limitations, lands on 3 Oct.

## How it works (target)

The model proposes; deterministic code disposes. Every interaction runs **Understand -> Decide -> Act -> Verify -> Escalate**.

| Stage | What it does | Technology |
| --- | --- | --- |
| Identity and guards | The customer logs in with a credential; the API verifies the session token and takes `customer_id` only from it; PII is masked before any model call | Supabase Auth (ES256 tokens verified against the project JWKS), FastAPI |
| Understand | Reads the masked message: intent, stolen card, distress, amount, date, merchant | Jev (TypeSafe AI) typed signals, with a keyword and regex extractor as fallback and baseline |
| Decide | Applies the dispute policy clause by clause, plus a fraud-risk score | Policy as code (clause ids such as `POL-WIN-60`, `POL-ESC-500`); LightGBM without the leaky `fraud_score` |
| Act and Verify | Opens the case or locks the card, then reads the record back before telling the customer | Tool gateway on Supabase Postgres (`ops` schema) with idempotency keys and an append-only audit log |
| Escalate | Sends legal, high-value, high-risk, multi-charge, distress and still-ambiguous cases to a human | Structured handoff packet and an English review console |
| Converse and explain | Writes replies in Spanish or Portuguese from verified facts; explains the policy with citations | Claude Haiku 4.5 with placeholders filled by code; RAG over a team-written policy text with local embeddings |

The full component diagram is in [`docs/PLAN.md`](docs/PLAN.md) ("Arquitectura del sistema"). Deployment: Vercel for the API and the React front, Supabase for identity and the operational database, both on free plans.

## What runs today

- **Reference baseline** (the starter pipeline, wired to the API): `/health`, plus `/api/v1/sanitize`, `/api/v1/triage`, `/api/v1/hitl/queue` and `/api/v1/hitl/resolve`, which answer only when `APP_ENV` is development or test. English keyword rules and mock tools. It is measured as is in the evaluation and is not deployed.
- **Dispute stack** (wired since 27 Sep, behind the session token): the policy engine v2.3 (`src/rules/dispute_policy.py`, spec `docs/specs/dispute-policy-v2.3.md`), the Understand router (`src/understand/`: Jev typed signals when a key and the daily budget allow, the ES/PT keyword extractor otherwise), the five-stage orchestrator (`src/orchestrator/`), the operational store on DuckDB or Postgres (`src/ops/`, DDL in `supabase/migrations/0001_ops.sql`), the act-and-verify gateway over the lakehouse or the Postgres serving copy (`src/tools/`), and the API: customer chat at `/api/v1/disputes/...`, the English HITL console at `/api/v1/console/...` (agent role), and a local test issuer at `/api/v1/auth/...` (dev and test only, until Supabase Auth). Swagger lists them.
- **Data pipeline**: S3 CSVs into a local DuckDB lakehouse (bronze, silver, gold) over a customer-aligned sample of 25,000 customers (`src/data/ingestion.py`), plus the full 2023 to 2026 history in a separate file for the ML work.
- **Evaluation harness** (`src/eval/`): scripted cases in JSONL (`data/eval/dev_cases.jsonl`, 18 team-generated development cases in ES and PT), runners for the proposed stack (rules-only mode today) and the reference baseline (the starter pipeline through an adapter), the brief's metrics as counts over denominators with slices by language, segment and country, and a Markdown report (`reports/eval_dev.md`).
- **Risk model** (`src/ml/fraud_risk_transfer.py`): the bank's fraud label is random, so the served score is trained on the IEEE-CIS competition over the deployable contract features (spec `docs/specs/fraud-risk-model-v1-ieee-cis.md`), with the escalation threshold at percentile 98 of the bank's Web and App window. `TransferRiskScorer` (`src/ml/transfer_scorer.py`) feeds `POL-ESC-ML-RISK` and the handoff's risk explanation when `models/fraud_risk_ieee.joblib` exists, and every training run is logged to MLflow. The earlier leak-free pipeline on bank features (`src/ml/fraud_risk.py`) stays as the evidence: on the full history its test ROC AUC is 0.497.
- **Analysis notebooks**: [`notebooks/01_problema_y_datos.ipynb`](notebooks/01_problema_y_datos.ipynb), the data behind the workflow choice; [`notebooks/02_risk_model_experiment.ipynb`](notebooks/02_risk_model_experiment.ipynb), why the fraud label cannot be learned without the leak; [`notebooks/03_fraud_signal_search.ipynb`](notebooks/03_fraud_signal_search.ipynb), the search for a fraud signal across every other table (needs `data/lakehouse_aux.duckdb` from `scripts/data_ops/load_aux_tables.py`). Run a notebook with `uv run python scripts/notebooks/run_notebook.py <path>`.
- **Tests**: CI runs the suite on every PR against a Postgres service. The 6 in `tests/test_data_integrity.py` need a local `data/lakehouse.duckdb` and skip without it; the Postgres tests (`tests/test_ops_store.py`, `tests/test_gateway_postgres.py`, `tests/test_publish_serving.py`) run only with `TEST_DATABASE_URL` set.

## Quick start

Prerequisites: Python 3.11 locally (`.python-version`; CI and the Docker images run 3.12) and [`uv`](https://github.com/astral-sh/uv), or only Docker: `docker compose run --rm dev <command>` runs any Python command below in a Linux container, the same on Mac and Windows. Building the lakehouse needs the read-only AWS keys from the data dictionary in a git-ignored `.env`; never commit them.

```bash
uv sync                                               # install from the lockfile
uv run pytest -v                                      # test suite
docker compose run --rm dev                           # test suite as CI runs it (Linux, Python 3.12, Postgres 17), no local Python needed
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

Run commands from the repo root: `data/lakehouse.duckdb` is a relative path. The dispute API needs the lakehouse for bank facts; the operational store (`data/ops.duckdb`, or `OPS_DB_PATH=postgresql://...`) is created on first use. Try it: `GET /api/v1/auth/personas`, `POST /api/v1/auth/test-session`, then chat at `POST /api/v1/disputes/conversations` and `.../messages` with the bearer token.

## Data

LATAM Bank Dataset v1.0.0 from the organizers: 100% synthetic, about 19 million rows in 13 tables, Mexico, Colombia and Argentina, all text in Spanish. There is no Portuguese in the data, so every Portuguese case is team-generated and labeled as such. Findings that shape the design, such as `fraud_score` leaking the fraud label and transaction timestamps offset from the processing day, are in [`AGENTS.md`](AGENTS.md) section 7.

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
| [`docs/reviews/`](docs/reviews/) | Spanish | Adversarial review of the plan and reuse review of a starter repo |

## Ground rules

These come from the official problem statement; breaking one disqualifies the work.

- Identity comes from a verified session, never from a customer or document number alone.
- Permissions and policy live in code, never in prompts. The model proposes; code decides.
- Only actions verified by reading back from the system of record are reported as done.
- No real money movement or credit decisions: provisional credit is at most a flag a human reviews.
- No credentials or private records in the repo or in calls to external models.
- Limits are stated honestly: data, language coverage, capacity and deployment.
