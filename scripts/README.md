# Scripts & Operational Tooling Directory

This directory contains standalone operational, audit, inspection, and automation tools supporting the OmniGuard AI Lakehouse and evaluation workflows.

---

## Directory Structure

```
scripts/
├── audit/
│   ├── check_data_consistency.py   # Comprehensive lakehouse schema, PK/FK, null & trap audit
│   └── inspect_lakehouse.py        # Lightweight table, column, and row count inspector
├── data_ops/
│   ├── inspect_s3_schemas.py       # Flexible S3 partition & schema inspector (CLI parameterized)
│   └── verify_s3_connection.py     # End-to-end Boto3 & DuckDB HTTPFS connectivity tester
├── deploy/
│   └── vercel_build.py             # Vercel build step: compiles the React front (pyproject [tool.vercel.scripts])
└── notebooks/
    └── run_notebook.py             # Headless execution of Jupyter notebooks (nbclient)
```

---

## Quick Reference Commands

### 1. Data Quality & Lakehouse Audits (`scripts/audit/`)

- **Comprehensive Consistency & Trap Audit**:
  Audits primary key uniqueness, foreign key referential integrity (checking for orphan records), null distributions, date offsets (UTC-6 vs plain cast), and tests for `fraud_score` label leakage.
  ```bash
  uv run python scripts/audit/check_data_consistency.py
  ```

- **Quick Table & Column Inspection**:
  Quickly lists all bronze, silver, and gold tables, column names, and row counts in `data/lakehouse.duckdb`.
  ```bash
  uv run python scripts/audit/inspect_lakehouse.py
  ```

---

### 2. S3 & Remote Lakehouse Diagnostics (`scripts/data_ops/`)

- **Verify S3 Credentials & HTTPFS Connection**:
  Tests read permissions, lists key S3 prefixes via Boto3, and verifies that DuckDB's `httpfs` extension can query remote CSV files.
  ```bash
  uv run python scripts/data_ops/verify_s3_connection.py
  ```

- **Inspect Remote S3 Schemas & Partitions**:
  Inspect all tables:
  ```bash
  uv run python scripts/data_ops/inspect_s3_schemas.py
  ```
  Inspect a specific table with a custom sample size:
  ```bash
  uv run python scripts/data_ops/inspect_s3_schemas.py --table transactions --limit 5
  uv run python scripts/data_ops/inspect_s3_schemas.py --table complaints --limit 3
  ```

---

### 3. Notebook Automation (`scripts/notebooks/`)

- **Execute Analysis Notebook Headlessly**:
  Executes `notebooks/01_problema_y_datos.ipynb` end-to-end using `nbclient`, refreshing all generated outputs and figures without needing a graphical Jupyter kernel.
  ```bash
  uv run python scripts/notebooks/run_notebook.py
  ```

---

## Backward Compatibility Note

Root-level forwarders are maintained for existing CI pipelines and documentation references (`scripts/check_data_consistency.py`, `scripts/inspect_lakehouse.py`, `scripts/run_notebook.py`).
