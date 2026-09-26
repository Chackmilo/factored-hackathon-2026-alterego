"""
Data ingestion pipeline for OmniGuard AI Lakehouse (Bronze -> Silver -> Gold).
Uses DuckDB with native S3 reading, Pandera/SQL validation, and Composite Business Key deduplication.
"""
import os
import time
from pathlib import Path
import duckdb
from rich.console import Console
from src.data.db import get_db_connection

console = Console()

# Reference anchor date for hackathon dataset: 2026-06-17 (UTC-6 process_date)
ANCHOR_DATE = "2026-06-17"

def run_ingestion_pipeline(sample_only: bool = True):
    """
    Executes the Lakehouse ingestion pipeline:
    1. Bronze: Ingest raw CSV data from S3 or local files.
    2. Silver: Deduplicate via Composite Business Key, clean nulls, quarantine anomalies.
    3. Gold: Enriched marts (currency conversion, 60-day policy flags, customer profiles).
    """
    bucket = os.getenv("S3_BUCKET_NAME", "factored-datathon-2026-s3-157725502942-us-east-2-an")
    start_time = time.time()
    
    console.print(f"[bold cyan]Starting Lakehouse Ingestion Pipeline (sample_only={sample_only})[/bold cyan]")
    con = get_db_connection()
    
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
    
    # Transactions (Active window 2026)
    console.print("Ingesting Transactions...")
    trx_path = f"s3://{bucket}/data/transactions/year=2026/month=06/*/*.csv" if sample_only else f"s3://{bucket}/data/transactions/year=2026/*/*/*.csv"
    con.execute(f"""
        CREATE OR REPLACE TABLE bronze_transactions AS 
        SELECT * FROM read_csv_auto('{trx_path}'){sample_filter};
    """)
    trx_count = con.execute("SELECT COUNT(*) FROM bronze_transactions").fetchone()[0]
    console.print(f" -> [green]bronze_transactions[/green]: {trx_count:,} rows")
    
    # ----------------------------------------------------
    # 2. SILVER LAYER (Deduplication via Business Key & Quarantine)
    # ----------------------------------------------------
    console.print("\n[yellow]Building Silver Layer with Business-Key Deduplication...[/yellow]")
    
    # Quarantine duplicates for transactions
    con.execute("""
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
    """)
    dups_trx = con.execute("SELECT COUNT(*) FROM quarantine_duplicate_transactions").fetchone()[0]
    console.print(f" -> [magenta]quarantine_duplicate_transactions[/magenta]: {dups_trx:,} duplicates isolated")
    
    # Clean Silver Transactions
    con.execute("""
        CREATE OR REPLACE TABLE silver_transactions AS
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
        WHERE duplicate_rank = 1;
    """)
    silver_trx_count = con.execute("SELECT COUNT(*) FROM silver_transactions").fetchone()[0]
    console.print(f" -> [green]silver_transactions[/green]: {silver_trx_count:,} clean transactions")
    
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
    
    # Gold Transactions (Normalized with USD amount, 60-day filing window check, card details)
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
            -- Calculate normalized amount in USD
            CASE 
                WHEN t.currency = 'USD' THEN t.amount
                WHEN t.amount_usd IS NOT NULL THEN t.amount_usd
                ELSE ROUND(t.amount * COALESCE(xr_daily.exchange_rate, xr_latest.exchange_rate, 1.0), 2)
            END as amount_usd_normalized,
            t.channel,
            COALESCE(t.merchant_name, 'Unknown Merchant') as merchant_name,
            t.merchant_category,
            t.transaction_country,
            t.transaction_city,
            t.transaction_status,
            t.is_fraud,
            t.fraud_score,
            -- Dispute Policy Window Check (<= 60 calendar days from anchor date using bank process_date UTC-6)
            (DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{ANCHOR_DATE}') <= 60 
             AND DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{ANCHOR_DATE}') >= 0) as is_within_60_days,
            DATE_DIFF('day', CAST(t.process_date AS DATE), DATE '{ANCHOR_DATE}') as days_since_transaction
        FROM silver_transactions t
        LEFT JOIN silver_products p ON t.product_id = p.product_id
        LEFT JOIN bronze_daily_exchange_rates xr_daily 
            ON t.currency = xr_daily.source_currency 
            AND xr_daily.target_currency = 'USD' 
            AND CAST(t.process_date AS DATE) = xr_daily.date
        LEFT JOIN gold_exchange_rates xr_latest 
            ON t.currency = xr_latest.source_currency 
            AND xr_latest.target_currency = 'USD';
    """)
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
