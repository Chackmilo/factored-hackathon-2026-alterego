"""
Load the auxiliary fact tables (call center interactions, transcripts, surveys, digital events, campaign sends)
and the two remaining dimensions into data/lakehouse_aux.duckdb, month by month with retries, for the fraud
signal search (notebooks/03_fraud_signal_search.ipynb). Read-only S3 keys from .env; nothing is written back.

    uv run python scripts/data_ops/load_aux_tables.py [--db data/lakehouse_aux.duckdb] [--tables call_center_interactions,...]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.data.ingestion import (  # noqa: E402
    DATASET_FIRST_MONTH,
    DATASET_LAST_MONTH,
    transaction_month_globs,
)

FACT_TABLES = ("call_center_interactions", "call_transcripts", "satisfaction_surveys", "digital_events", "campaign_sends")
# The two heavy tables (10M and 2M rows) are loaded for the last twelve months of the dataset by default; the fraud label
# is uniform over time, so the window keeps about 1,400 fraud charges for the signal search. Override with --first-month.
HEAVY_TABLES_FIRST_MONTH = {"digital_events": (2025, 7), "campaign_sends": (2025, 7)}
DIMENSIONS = ("service_agents", "marketing_campaigns")
HIVE = "hive_partitioning=true, hive_types={'year': BIGINT, 'month': VARCHAR, 'day': VARCHAR}"


def connect(db_path: str) -> duckdb.DuckDBPyConnection:
    load_dotenv(".env")
    con = duckdb.connect(db_path)
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{os.getenv('AWS_DEFAULT_REGION', 'us-east-2')}';")
    con.execute(f"SET s3_access_key_id='{os.getenv('AWS_ACCESS_KEY_ID')}'; SET s3_secret_access_key='{os.getenv('AWS_SECRET_ACCESS_KEY')}';")
    con.execute("SET http_timeout=120000; SET http_retries=5; SET http_retry_wait_ms=2000; SET http_retry_backoff=2;")
    return con


def load_fact(con: duckdb.DuckDBPyConnection, bucket: str, table: str, retries: int = 3, first_month: tuple[int, int] | None = None) -> int:
    first = first_month or HEAVY_TABLES_FIRST_MONTH.get(table, DATASET_FIRST_MONTH)
    patterns = [p.replace("/transactions/", f"/{table}/") for p in transaction_month_globs(f"s3://{bucket}/data", first, DATASET_LAST_MONTH)]
    con.execute(f"DROP TABLE IF EXISTS {table}")
    created, chunks = False, 0
    for pattern in patterns:
        for attempt in range(1, retries + 1):
            try:
                if not created:
                    con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{pattern}', {HIVE})")
                    created = True
                else:
                    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_csv_auto('{pattern}', {HIVE})")
                chunks += 1
                break
            except duckdb.IOException as exc:
                if "No files found" in str(exc):
                    break
                if attempt == retries:
                    raise
                print(f"  retry {attempt} for {pattern}: {str(exc)[:100]}", flush=True)
                time.sleep(5 * attempt)
        print(f"  {table}: {chunks} months loaded", flush=True)
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/lakehouse_aux.duckdb")
    parser.add_argument("--tables", default=",".join(FACT_TABLES))
    parser.add_argument("--first-month", default=None, help="YYYY-MM to override the first month for every table")
    args = parser.parse_args()
    bucket = os.getenv("S3_BUCKET_NAME", "factored-datathon-2026-s3-157725502942-us-east-2-an")
    con = connect(args.db)
    for dim in DIMENSIONS:
        con.execute(f"CREATE OR REPLACE TABLE {dim} AS SELECT * FROM read_csv_auto('s3://{bucket}/data/{dim}.csv')")
        print(f"{dim}: {con.execute(f'SELECT COUNT(*) FROM {dim}').fetchone()[0]:,} rows", flush=True)
    for table in args.tables.split(","):
        started = time.time()
        override = tuple(int(x) for x in args.first_month.split("-")) if args.first_month else None
        n = load_fact(con, bucket, table, first_month=override)
        print(f"{table}: {n:,} rows in {time.time() - started:.0f} s", flush=True)
    con.close()
    print("AUX LOAD COMPLETED", flush=True)


if __name__ == "__main__":
    main()
