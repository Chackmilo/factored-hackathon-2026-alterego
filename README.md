# AlterEgo: transaction-dispute intake for LATAM Bank

Team AlterEgo's submission to the **Factored AI & Data Hackathon 2026**: an AI-first customer-service system for one workflow, **transaction-dispute intake**, in Spanish and Portuguese. The agent finds the charge the customer does not recognize, checks it against a written dispute policy, opens a case and confirms it only after reading it back, protects the customer with a card lock they confirm, and hands off to a human with a structured packet when the case needs one. It never moves money.

> **Status (2026-09-26, day 2 of 10).** Planning is closed (gate G0) and the build starts on 27 Sep. This README describes the plan and the code that runs today. The final README, with results, the deployment URL and limitations, lands on 3 Oct.

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

- **Reference baseline** (the starter pipeline, wired to the API): `/health`, `/api/v1/sanitize`, `/api/v1/triage`, `/api/v1/hitl/queue`, `/api/v1/hitl/resolve`. English keyword rules and mock tools. It is measured as is in the evaluation and is not deployed.
- **Dispute stack pieces**, not yet wired to the API: the dispute policy engine (`src/rules/dispute_policy.py`), the act-and-verify tool gateway over DuckDB (`src/tools/gateway.py`), JWT test sessions (`src/auth/session.py`, to be replaced by Supabase Auth) and the handoff packet model (`src/domain/handoff.py`).
- **Data pipeline**: S3 CSVs into a local DuckDB lakehouse (bronze, silver, gold) over a customer-aligned sample of 25,000 customers (`src/data/ingestion.py`).
- **Analysis notebook**: [`notebooks/01_problema_y_datos.ipynb`](notebooks/01_problema_y_datos.ipynb), the data behind the workflow choice.
- **Tests**: 36 pass. The 6 in `tests/test_data_integrity.py` need a local `data/lakehouse.duckdb` and skip without it.

## Quick start

Prerequisites: Python 3.11 (the team moves to 3.12 on 27 Sep) and [`uv`](https://github.com/astral-sh/uv). Building the lakehouse needs the read-only AWS keys from the data dictionary in a git-ignored `.env`; never commit them.

```bash
uv sync                                               # install from the lockfile
uv run pytest -v                                      # test suite
uv run uvicorn src.api.app:app --reload --port 8000   # API, Swagger at http://localhost:8000/docs
uv run python main.py                                 # baseline demo over data/synthetic_samples.json
uv run python -m src.data.ingestion                   # build data/lakehouse.duckdb from S3
docker-compose up --build -d                          # containerized API
```

Run commands from the repo root: `data/lakehouse.duckdb` is a relative path.

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
