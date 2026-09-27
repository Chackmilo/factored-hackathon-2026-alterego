# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Read `AGENTS.md` before any non-trivial change: it holds the hackathon rules (violations disqualify the work), judging metrics, verified data findings (section 7), target architecture, the gap between code and plan (section 9), and a pointer to `docs/PLAN.md` (problem question, plan, roadmap, decision log). `docs/TEAM_BRIEF_COMPLEMENTED.md` (v2.4) holds the dispute policy spec, data contracts and evaluation spec; `docs/SUPABASE_VERCEL.md` holds the identity, database and deployment design; `src/rules/dispute_policy.py` and `src/data/ingestion.py` still implement v2.0 in places. This file covers only how to run the code and how it is wired today.

## Commands

```bash
uv sync                                               # install (Python 3.11, uv lockfile)
uv run pytest -v                                      # full suite
uv run pytest tests/test_dispute_flow.py::test_dispute_policy_high_value_escalation -v   # single test
uv run uvicorn src.api.app:app --reload --port 8000   # API, Swagger at /docs
uv run python main.py                                 # baseline demo over data/synthetic_samples.json
uv run python -m src.data.ingestion                   # build data/lakehouse.duckdb from S3 (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY in .env)
docker-compose up --build -d                          # containerized API
uvx ruff check <files you touched>                    # lint (ruff is not a project dependency)
```

Ruff config lives in `pyproject.toml`. The tree is not lint-clean yet (about 200 findings on 26-Sep), so lint and `--fix` only the files you change. pytest runs with `pythonpath = ["."]`, so imports are absolute from the repo root (`from src.rules.dispute_policy import ...`). Operational scripts are organized in `scripts/audit/`, `scripts/data_ops/`, and `scripts/notebooks/` (see `scripts/README.md`), with root-level forwarders for backward compatibility.

## Architecture: two stacks side by side

The repo holds two decision paths. Know which one you are touching.

**Decided but not yet in code (26-Sep):** Supabase Auth replaces `src/auth/session.py`, and Supabase Postgres (`bank` read-only serving copy, `ops` for writes) replaces the gateway's DuckDB reads and writes and the planned SQLite store. Deployment moves to Vercel (decided), on free plans, and the stack moves to Python 3.12 (decided). Everything below describes the code as it runs today; see `docs/SUPABASE_VERCEL.md` before touching auth, the gateway or deployment.

**Baseline (wired to the API and `main.py`).** `src/api/app.py` calls `HybridOrchestrator` in `src/agents/orchestrator.py`: a single-shot pipeline of `PIIMasker`, then `DeterministicRulesEngine` (`src/rules/engine.py`), then the hand-tuned `MLFraudDetector`, then a keyword branch calling always-succeeding mocks in `src/agents/tools.py`, with escalations going to the in-memory `hitl_queue`. It takes `customer_id` from the request body, is USD only and simulates LLM tokens. The team decided (26-Sep) to measure it as the reference baseline as is, with only its crash fixed: do not repair its unsafe behavior (it counts in the report), build dispute features in the dispute stack, and never deploy it (its in-memory queue cannot work on stateless Vercel functions).

**Dispute stack (new; exercised only by `tests/test_dispute_flow.py`, not yet wired into the API or an orchestrator).**

- `src/auth/session.py`: HS256 JWT test sessions. `create_test_session` mints tokens; `get_current_session` is the FastAPI dependency that yields a `VerifiedSession`. Gateway tools take this session, never a raw `customer_id`.
- `src/rules/dispute_policy.py`: `DisputePolicyEngine.evaluate` checks clauses in a fixed order and returns on the first match: window `POL-WIN-60`, regulator or legal keywords `POL-ESC-LEGAL`, amount over $500 `POL-ESC-500`, ML risk over 0.70 `POL-ESC-ML-RISK`, more than 2 charges in 48h `POL-ESC-MULTI`, simulated provisional credit `POL-AUT-150`, plain intake `POL-AUT-INTAKE`. Reordering changes outcomes. Customer-facing text is `explanation_es` / `explanation_pt`, templated from the decision.
- `src/tools/gateway.py`: `BankingToolGateway` act-and-verify tools. Each mutation checks ownership against the silver tables (`UnauthorizedAccessError`), writes, then reads back (`ActionVerificationError` when the read-back disagrees, and also when the product or transaction does not exist; `RecordNotFoundError` is raised only by `get_customer_profile`). Merchant names leave the gateway wrapped in `<untrusted_merchant_data>` tags as the prompt-injection boundary.
- `src/domain/handoff.py`: `StructuredHandoffPacket`, the HITL handoff contract.
- `src/data/`: DuckDB lakehouse at `data/lakehouse.duckdb`. `ingestion.py` reads CSVs straight from S3 into `bronze_*`, deduplicates on composite business keys into `silver_*` (transaction duplicates land in `quarantine_duplicate_transactions`), and builds `gold_transactions` (USD normalization, window flags) and `gold_customers` (account age, complaints in the last 90 days). The default `sample_only=True` loads 25k customers plus only their products, 2026 complaints and June 2026 transactions, so foreign keys line up (the dataset's intentional orphan-FK trap shows only with `sample_only=False`).

## Gotchas

- **"Today" is 2026-06-17**, the dataset end date. It is hardcoded three times: `ANCHOR_DATE` at the top of `ingestion.py`, a local `ANCHOR_DATE` that shadows it in the gold-layer block (the one gold SQL actually uses), and the default `DisputePolicyInput.current_date`. Window and account-age math uses it, not the wall clock. Keep all three in sync.
- **Event time is offset.** Each daily partition spans 06:00 to 05:59 of the next day, so `process_date` = date(`transaction_date` - 6 h). `CAST(transaction_date AS DATE)` misdates about 24% of rows and gives 227 sampled charges a day count of -1. Use `process_date` for window and velocity math (AGENTS.md section 7).
- **`fraud_score` leaks `is_fraud`** (every non-fraud row scores <= 30). It stays in `gold_transactions` for analysis only; models and the baseline use it nowhere. The `fraud_score` fields in `src/domain/schemas.py`, `src/hitl/queue.py` and the orchestrator are a name collision: they carry `MLFraudDetector.fraud_probability`, not the dataset column.
- **Gateway reads hit `gold_*`, gateway writes hit `silver_*`.** Gold tables are materialized snapshots: after a card lock `gold_transactions.product_status` stays stale, and a new dispute does not raise `gold_customers.complaints_last_90d`, until ingestion reruns. The Supabase design removes this for the app: live views over `bank` plus `ops` (`docs/SUPABASE_VERCEL.md` section 4.5).
- Gateway tests run against the team-generated `fixture_db` in `tests/test_dispute_flow.py`, never the real lakehouse. Point `BankingToolGateway(db_path=...)` at a fixture the same way for new tool tests. `tests/conftest.py` offers shared fixtures (`client`, `auth_headers`, `sample_dispute_input`) for new tests; no existing test uses them yet (`test_api.py` builds its own module-level client).
- `tests/test_data_integrity.py` is the one suite that reads the real `data/lakehouse.duckdb`, and it skips silently when the file is missing. A green run without the lakehouse has not checked the data.
- `data/lakehouse.duckdb` is a relative path, so run commands from the repo root. It is git-ignored; rebuild it with the ingestion command.
- `.env.example` omits the AWS keys (they come from the data dictionary PDF). Without them `get_db_connection` in `src/data/db.py` silently skips the S3 setup, so ingestion fails later at the first S3 read, not at connect. `S3_BUCKET_NAME` and `AWS_DEFAULT_REGION` have working defaults.
- DuckDB allows one writer process. An open notebook kernel or other process holding `data/lakehouse.duckdb` makes ingestion and the gateway fail with "Cannot open file ... being used by another process".
- Thresholds live in two places: the dispute policy hardcodes its own in `dispute_policy.py`; the env thresholds in `src/core/config.py` (`MAX_AUTONOMOUS_TRANSACTION_LIMIT` and friends) feed only the baseline.
- **Open conflict:** `POL-AUT-150` returns simulated provisional credit as an autonomous outcome (brief v2.0), while AGENTS.md rule 8 allows provisional credit only as a recommendation. The team decided (26-Sep, `docs/PLAN.md`) that it is a candidate flag a human approves in the HITL console; the code still has to change.
