"""
Data ingestion pipeline for OmniGuard AI Lakehouse (Bronze -> Silver -> Gold).
Uses DuckDB with native S3 reading, Pandera/SQL validation, and Composite Business Key deduplication.
"""
import os
import time
from pathlib import Path

from rich.console import Console

from src.data.db import get_db_connection

console = Console()

# Reference anchor date for hackathon dataset: 2026-06-17 (UTC-6 process_date)
ANCHOR_DATE = "2026-06-17"

def transactions_glob(root: str, sample_only: bool) -> str:
    """Partition glob for transactions under root (e.g. s3://<bucket>/data): June 2026 for the sample, every year for the full load."""
    return f"{root}/transactions/year=2026/month=06/*/*.csv" if sample_only else f"{root}/transactions/*/*/*/*.csv"


class IngestionContractError(RuntimeError):
    """A data contract failed; the load stops rather than writing a wrong value."""


SILVER_TRANSACTIONS_SQL = """
    CREATE OR REPLACE TABLE silver_transactions AS
    WITH ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY customer_id, amount, currency, COALESCE(merchant_name, 'UNKNOWN'), DATE_TRUNC('minute', transaction_date)
                ORDER BY process_date DESC
            ) as duplicate_rank
        FROM bronze_transactions
    ),
    clean AS (
        SELECT * EXCLUDE (duplicate_rank) FROM ranked WHERE duplicate_rank = 1
    ),
    rated AS (
        SELECT c.*, x.exchange_rate AS daily_rate
        FROM clean c
        LEFT JOIN bronze_daily_exchange_rates x
            ON x.source_currency = c.currency AND x.target_currency = 'USD' AND CAST(x.date AS DATE) = CAST(c.process_date AS DATE)
    )
    SELECT * EXCLUDE (amount_usd, daily_rate),
        -- the raw dataset value, untouched: the rollback path (team decision TQ-001, 27-Sep)
        amount_usd AS amount_usd_legacy,
        -- the fixed value every downstream table reads
        CASE WHEN currency = 'USD' THEN amount
             WHEN amount_usd IS NOT NULL THEN amount_usd
             ELSE ROUND(amount * daily_rate, 2) END AS amount_usd,
        CASE WHEN currency = 'USD' THEN 'same_currency'
             WHEN amount_usd IS NOT NULL THEN 'native'
             ELSE 'daily_rate_fill' END AS amount_usd_source,
        CASE WHEN currency <> 'USD' AND amount_usd IS NULL THEN daily_rate END AS amount_usd_fx_rate
    FROM rated;
"""


QUARANTINE_DUPLICATE_TRANSACTIONS_SQL = """
    CREATE OR REPLACE TABLE quarantine_duplicate_transactions AS
    WITH ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY customer_id, amount, currency, COALESCE(merchant_name, 'UNKNOWN'), DATE_TRUNC('minute', transaction_date)
                ORDER BY process_date DESC
            ) as duplicate_rank
        FROM bronze_transactions
    )
    SELECT * EXCLUDE (duplicate_rank)
    FROM ranked
    WHERE duplicate_rank > 1;
"""


def build_quarantine_duplicate_transactions(con) -> None:
    """The rows silver leaves out: every copy of a business key but the one with the latest process day (a late reprocess wins)."""
    con.execute(QUARANTINE_DUPLICATE_TRANSACTIONS_SQL)


def build_silver_transactions(con) -> None:
    """Deduplicate on the business key and fix amount_usd at silver: USD rows copy the amount, native values stay,
    COP and ARS gaps are filled from the daily mid rate of the process day. A non-USD row with neither a native
    value nor a rate fails the load (never the 1.0 fallback that treated pesos as dollars)."""
    con.execute(SILVER_TRANSACTIONS_SQL)
    unresolved = con.execute("SELECT COUNT(*) FROM silver_transactions WHERE amount_usd IS NULL").fetchone()[0]
    if unresolved:
        sample = con.execute("SELECT transaction_id, currency, process_date FROM silver_transactions WHERE amount_usd IS NULL LIMIT 3").fetchall()
        raise IngestionContractError(f"{unresolved} transactions have no amount_usd and no daily exchange rate for their process day, for example {sample}")


def build_gold_transactions(con, anchor_date: str) -> None:
    """Gold carries only the values the app needs, with amount_usd already fixed at silver (TQ-003)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE gold_transactions AS
        SELECT
            t.transaction_id,
            t.transaction_date,
            t.process_date,
            t.customer_id,
            t.product_id,
            p.product_type,
            p.product_status,
            t.transaction_type,
            t.amount,
            t.currency,
            t.amount_usd,
            t.amount_usd_source,
            t.channel,
            -- the dataset never gives these five types a merchant (0 of 3.34 M rows): it does not apply; a purchase without one lost it
            CASE WHEN t.merchant_name IS NOT NULL THEN t.merchant_name
                 WHEN t.transaction_type IN ('Withdrawal', 'Transfer', 'Payment', 'Deposit', 'Adjustment') THEN 'Not Applicable'
                 ELSE 'Unknown Merchant' END as merchant_name,
            t.merchant_category,
            t.transaction_country,
            t.transaction_city,
            t.transaction_status,
            t.is_fraud,
            t.fraud_score,  -- analysis only: it leaks the label (AGENTS.md section 7); models and the baseline never read it
            -- Dispute Policy Window Check (<= 60 calendar days from anchor date using bank process_date UTC-6)
            (DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{anchor_date}') <= 60
             AND DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{anchor_date}') >= 0) as is_within_60_days,
            DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{anchor_date}') as days_since_transaction
        FROM silver_transactions t
        LEFT JOIN silver_products p ON t.product_id = p.product_id;
    """)


DATASET_FIRST_MONTH = (2023, 6)
DATASET_LAST_MONTH = (2026, 6)


def transaction_month_globs(root: str, first: tuple[int, int] = DATASET_FIRST_MONTH, last: tuple[int, int] = DATASET_LAST_MONTH) -> list[str]:
    """One glob per month of the dataset period, so a failed month can be retried without redoing the rest."""
    year, month = first
    out = []
    while (year, month) <= last:
        out.append(f"{root}/transactions/year={year}/month={month:02d}/*/*.csv")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def ingest_transactions_chunked(con, patterns: list[str], sample_filter: str = "", retries: int = 3, wait_seconds: float = 5.0,
                                log=None, sleep=time.sleep, execute=None) -> int:
    """Load bronze_transactions chunk by chunk. A chunk that fails on an IO error is retried with backoff; a
    pattern that matches no file is skipped (the dataset has no partitions before 2023-06-17). The hive columns
    are typed explicitly (year BIGINT, month and day VARCHAR with their leading zeros), which is what the June
    sample load inferred; autocasting them per chunk crashes DuckDB 1.5 on small partitions."""
    import duckdb as _duckdb

    execute = execute or con.execute  # injectable for tests (a DuckDB connection's execute cannot be patched)
    execute("DROP TABLE IF EXISTS bronze_transactions")
    created = False
    loaded_chunks = 0
    for pattern in patterns:
        for attempt in range(1, retries + 1):
            try:
                if not created:
                    execute(f"CREATE TABLE bronze_transactions AS SELECT * FROM read_csv_auto('{pattern}', hive_partitioning=true, hive_types={{'year': BIGINT, 'month': VARCHAR, 'day': VARCHAR}}){sample_filter};")
                    created = True
                else:
                    execute(f"INSERT INTO bronze_transactions BY NAME SELECT * FROM read_csv_auto('{pattern}', hive_partitioning=true, hive_types={{'year': BIGINT, 'month': VARCHAR, 'day': VARCHAR}}){sample_filter};")
                loaded_chunks += 1
                break
            except _duckdb.IOException as exc:
                message = str(exc)
                if "No files found" in message or "no files" in message.lower():
                    break  # month without partitions
                if attempt == retries:
                    raise IngestionContractError(f"Chunk {pattern} failed after {retries} attempts: {message[:200]}") from exc
                if log:
                    log(f" [yellow]retry {attempt}/{retries - 1} for {pattern}: {message[:120]}[/yellow]")
                sleep(wait_seconds * attempt)
    if not created:
        raise IngestionContractError("No transaction partition could be read")
    return loaded_chunks


def run_ingestion_pipeline(sample_only: bool = True, db_path: Path | None = None):
    """
    Executes the Lakehouse ingestion pipeline:
    1. Bronze: Ingest raw CSV data from S3 or local files.
    2. Silver: Deduplicate via Composite Business Key, clean nulls, quarantine anomalies.
    3. Gold: Enriched marts (currency conversion, 60-day policy flags, customer profiles).
    """
    bucket = os.getenv("S3_BUCKET_NAME", "factored-datathon-2026-s3-157725502942-us-east-2-an")
    start_time = time.time()

    console.print(f"[bold cyan]Starting Lakehouse Ingestion Pipeline (sample_only={sample_only})[/bold cyan]")
    con = get_db_connection(db_path) if db_path else get_db_connection()

    # ----------------------------------------------------
    # 1. BRONZE LAYER (Raw Ingestion)
    # ----------------------------------------------------
    console.print("[yellow]Ingesting Bronze Dimensions...[/yellow]")

    # Daily exchange rates
    con.execute(f"""
        CREATE OR REPLACE TABLE bronze_daily_exchange_rates AS 
        SELECT * FROM read_csv_auto('s3://{bucket}/data/daily_exchange_rates.csv');
    """)
    rates_count = con.execute("SELECT COUNT(*) FROM bronze_daily_exchange_rates").fetchone()[0]
    console.print(f" -> [green]bronze_daily_exchange_rates[/green]: {rates_count:,} rows")

    # Branches
    con.execute(f"""
        CREATE OR REPLACE TABLE bronze_branches AS 
        SELECT * FROM read_csv_auto('s3://{bucket}/data/branches.csv');
    """)
    branches_count = con.execute("SELECT COUNT(*) FROM bronze_branches").fetchone()[0]
    console.print(f" -> [green]bronze_branches[/green]: {branches_count:,} rows")

    # Customers (Take sample or full)
    console.print("Ingesting Customers...")
    cust_query = f"SELECT * FROM read_csv_auto('s3://{bucket}/data/customers.csv')"
    if sample_only:
        cust_query += " LIMIT 25000"
    con.execute(f"CREATE OR REPLACE TABLE bronze_customers AS {cust_query};")
    cust_count = con.execute("SELECT COUNT(*) FROM bronze_customers").fetchone()[0]
    console.print(f" -> [green]bronze_customers[/green]: {cust_count:,} rows")

    # Sample products and facts by the sampled customers so foreign keys stay aligned
    sample_filter = " WHERE customer_id IN (SELECT customer_id FROM bronze_customers)" if sample_only else ""

    # Products
    console.print("Ingesting Products...")
    prod_query = f"SELECT * FROM read_csv_auto('s3://{bucket}/data/products.csv'){sample_filter}"
    con.execute(f"CREATE OR REPLACE TABLE bronze_products AS {prod_query};")
    prod_count = con.execute("SELECT COUNT(*) FROM bronze_products").fetchone()[0]
    console.print(f" -> [green]bronze_products[/green]: {prod_count:,} rows")

    # Complaints (Active window 2026 or all if fast)
    console.print("Ingesting Complaints...")
    complaints_path = f"s3://{bucket}/data/complaints/year=2026/*/*/*.csv" if sample_only else f"s3://{bucket}/data/complaints/*/*/*/*.csv"
    con.execute(f"""
        CREATE OR REPLACE TABLE bronze_complaints AS 
        SELECT * FROM read_csv_auto('{complaints_path}'){sample_filter};
    """)
    complaints_count = con.execute("SELECT COUNT(*) FROM bronze_complaints").fetchone()[0]
    console.print(f" -> [green]bronze_complaints[/green]: {complaints_count:,} rows")

    # Transactions: the June 2026 sample in one read, or the whole history month by month with retries
    console.print("Ingesting Transactions...")
    if sample_only:
        patterns = [transactions_glob(f"s3://{bucket}/data", sample_only=True)]
    else:
        patterns = transaction_month_globs(f"s3://{bucket}/data")
    ingest_transactions_chunked(con, patterns, sample_filter=sample_filter, log=lambda msg: console.print(msg))
    trx_count = con.execute("SELECT COUNT(*) FROM bronze_transactions").fetchone()[0]
    console.print(f" -> [green]bronze_transactions[/green]: {trx_count:,} rows")

    # ----------------------------------------------------
    # 2. SILVER LAYER (Deduplication via Business Key & Quarantine)
    # ----------------------------------------------------
    console.print("\n[yellow]Building Silver Layer with Business-Key Deduplication...[/yellow]")

    build_quarantine_duplicate_transactions(con)
    dups_trx = con.execute("SELECT COUNT(*) FROM quarantine_duplicate_transactions").fetchone()[0]
    console.print(f" -> [magenta]quarantine_duplicate_transactions[/magenta]: {dups_trx:,} duplicates isolated")

    build_silver_transactions(con)
    silver_trx_count = con.execute("SELECT COUNT(*) FROM silver_transactions").fetchone()[0]
    console.print(f" -> [green]silver_transactions[/green]: {silver_trx_count:,} clean transactions (amount_usd filled from the daily rate where the CSV had none)")

    # Clean Silver Customers
    con.execute("""
        CREATE OR REPLACE TABLE silver_customers AS
        SELECT 
            customer_id,
            document_number,
            document_type,
            first_name,
            last_name,
            CONCAT(first_name, ' ', last_name) as full_name,
            email,
            mobile_phone,
            country,
            city,
            segment,
            credit_score,
            registration_date,
            customer_status,
            accepts_marketing
        FROM bronze_customers
        QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY last_updated DESC) = 1;
    """)
    silver_cust_count = con.execute("SELECT COUNT(*) FROM silver_customers").fetchone()[0]
    console.print(f" -> [green]silver_customers[/green]: {silver_cust_count:,} unique customers")

    # Clean Silver Products
    con.execute("""
        CREATE OR REPLACE TABLE silver_products AS
        SELECT *
        FROM bronze_products
        QUALIFY ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY last_updated DESC) = 1;
    """)
    silver_prod_count = con.execute("SELECT COUNT(*) FROM silver_products").fetchone()[0]
    console.print(f" -> [green]silver_products[/green]: {silver_prod_count:,} unique products")

    # Clean Silver Complaints
    con.execute("""
        CREATE OR REPLACE TABLE silver_complaints AS
        SELECT *
        FROM bronze_complaints
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY customer_id, category, subcategory, COALESCE(affected_product_id, 'UNKNOWN'), DATE_TRUNC('day', creation_date)
            ORDER BY process_date DESC
        ) = 1;
    """)
    silver_complaints_count = con.execute("SELECT COUNT(*) FROM silver_complaints").fetchone()[0]
    console.print(f" -> [green]silver_complaints[/green]: {silver_complaints_count:,} clean complaints")

    # ----------------------------------------------------
    # 3. GOLD LAYER (Dispute Marts & Policy Features)
    # ----------------------------------------------------
    console.print("\n[yellow]Building Gold Dispute Marts...[/yellow]")

    # Reference anchor date for hackathon dataset: 2026-06-17
    ANCHOR_DATE = "2026-06-17"

    # Gold Exchange Rates (Latest available rate per currency to USD)
    con.execute("""
        CREATE OR REPLACE TABLE gold_exchange_rates AS
        SELECT 
            source_currency,
            target_currency,
            exchange_rate,
            date as rate_date
        FROM bronze_daily_exchange_rates
        QUALIFY ROW_NUMBER() OVER (PARTITION BY source_currency, target_currency ORDER BY date DESC) = 1;
    """)
    console.print(" -> [green]gold_exchange_rates[/green] created")

    build_gold_transactions(con, ANCHOR_DATE)
    gold_trx_count = con.execute("SELECT COUNT(*) FROM gold_transactions").fetchone()[0]
    console.print(f" -> [green]gold_transactions[/green]: {gold_trx_count:,} enriched transactions")

    # Gold Customers (Customer Tier, Account Age, Active Cards, Recent Complaints Count)
    con.execute(f"""
        CREATE OR REPLACE TABLE gold_customers AS
        WITH recent_complaints AS (
            SELECT 
                customer_id,
                COUNT(*) as complaints_last_90d
            FROM silver_complaints
            WHERE DATE_DIFF('day', CAST(creation_date AS DATE), DATE '{ANCHOR_DATE}') <= 90
            GROUP BY customer_id
        ),
        active_products AS (
            SELECT 
                customer_id,
                COUNT(*) as active_product_count
            FROM silver_products
            WHERE product_status = 'Active'
            GROUP BY customer_id
        )
        SELECT 
            c.*,
            DATE_DIFF('day', CAST(c.registration_date AS DATE), DATE '{ANCHOR_DATE}') as account_age_days,
            (DATE_DIFF('day', CAST(c.registration_date AS DATE), DATE '{ANCHOR_DATE}') > 180) as is_account_mature,
            COALESCE(rc.complaints_last_90d, 0) as complaints_last_90d,
            COALESCE(ap.active_product_count, 0) as active_products
        FROM silver_customers c
        LEFT JOIN recent_complaints rc ON c.customer_id = rc.customer_id
        LEFT JOIN active_products ap ON c.customer_id = ap.customer_id;
    """)
    gold_cust_count = con.execute("SELECT COUNT(*) FROM gold_customers").fetchone()[0]
    console.print(f" -> [green]gold_customers[/green]: {gold_cust_count:,} enriched customer profiles")

    elapsed = time.time() - start_time
    console.print(f"\n[bold green][OK] Lakehouse Ingestion completed successfully in {elapsed:.1f}s[/bold green]")
    con.close()

if __name__ == "__main__":
    run_ingestion_pipeline(sample_only=True)
