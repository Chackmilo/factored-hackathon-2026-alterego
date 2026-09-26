# Data Architecture & Provenance Directory

This directory manages local lakehouse data files, test fixtures, and evaluation scenarios for the OmniGuard AI / AlterEgo banking dispute intake system.

---

## Storage & File Organization

```
data/
├── fixtures/                       # Deterministic test fixtures for unit and integration testing
│   └── abstention_pol_win_60.json  # Real 77-day charge fixture validating POL-WIN-60 abstention
├── synthetic_samples.json          # Starter baseline multi-turn test scenarios (team-generated)
├── lakehouse.duckdb                # Local DuckDB Lakehouse (git-ignored, rebuildable from S3)
└── README.md                       # This architecture and provenance documentation
```

---

## 3-Tier Lakehouse Architecture

The analytical and feature-generation platform is built on DuckDB (`src/data/ingestion.py`):

1. **Bronze Layer (`bronze_*`)**:
   - Exact raw snapshots ingested directly from S3 partitions (`us-east-2`).
   - Tables: `bronze_customers`, `bronze_products`, `bronze_branches`, `bronze_daily_exchange_rates`, `bronze_transactions`, `bronze_complaints`.
2. **Silver Layer (`silver_*`)**:
   - Deduplicated via Composite Business Keys (`[customer_id, transaction_date, amount, merchant_name]`).
   - Quarantined duplicates stored in `quarantine_duplicate_transactions`.
   - Data cleaning, null filtering, and type consistency enforcement.
3. **Gold Layer (`gold_*`)**:
   - Business-ready feature marts:
     - `gold_transactions`: USD normalized amounts (`amount_usd_normalized`), 60-day policy window flags (`is_within_60_days`, `days_since_transaction` using anchor date `2026-06-17`).
     - `gold_customers`: Precomputed dispute context (`account_age_days`, `is_account_mature`, `complaints_last_90d`, `active_products`).
     - `gold_exchange_rates`: Daily FX rates for currency conversions.

---

## Serving Layer (`bank` Schema in Supabase)

Per `docs/SUPABASE_VERCEL.md`:
- DuckDB remains **local-only** for data engineering, ingestion, and offline ML training.
- The web application connects to a **minimized serving subset** published to Supabase Postgres (`bank` schema).
- Minimized serving subset excludes `is_fraud`, `fraud_score`, card numbers, documents, and customer contact data to uphold Rule 10 (Zero Credential/PII exposure).

---

## Verified Data Traps & Invariants (Must Follow)

1. **Date Offset (`process_date` vs `transaction_date`)**:
   - Raw transaction partitions span `06:00 to 05:59` of the following day (bank processing day UTC-6).
   - Window calculations (`POL-WIN-60`) and velocity checks must use `process_date`, not a raw timestamp cast.
2. **Anchor Date**:
   - "Today" in the dataset is fixed at **`2026-06-17`** (the final date of synthetic transactions). Wall-clock time must not be used for window checks.
3. **Fraud Label Leakage (`fraud_score`)**:
   - In the organizer dataset, all non-fraud transactions have `fraud_score <= 30.0`. A score above 30 indicates fraud with 100% precision.
   - **`fraud_score` is strictly excluded from all machine learning features and policy rules.**
4. **Data Provenance Rules (Rule 4)**:
   - Every fixture, sample, or dataset artifact must be tagged:
     - `synthetic-organizer`: Ingested from organizer S3 bucket.
     - `team-generated`: Utterances, scenarios, or test fixtures created by the team (all Portuguese text is team-generated).
     - `derived`: Computed aggregates and normalized marts.
