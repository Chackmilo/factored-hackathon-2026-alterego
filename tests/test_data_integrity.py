"""
Tests for Data Integrity and Consistency in the DuckDB Lakehouse.
Ensures schemas, primary keys, referential integrity, date alignment,
and currency normalization remain consistent and error-free.
"""
from pathlib import Path
import duckdb
import pytest

LAKEHOUSE_PATH = Path("data/lakehouse.duckdb")

@pytest.fixture(scope="module")
def con():
    if not LAKEHOUSE_PATH.exists():
        pytest.skip("Lakehouse database file not found at data/lakehouse.duckdb")
    connection = duckdb.connect(str(LAKEHOUSE_PATH), read_only=True)
    yield connection
    connection.close()

def test_lakehouse_tables_exist(con):
    tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
    expected_tables = [
        "bronze_branches", "bronze_complaints", "bronze_customers",
        "bronze_daily_exchange_rates", "bronze_products", "bronze_transactions",
        "silver_complaints", "silver_customers", "silver_products", "silver_transactions",
        "gold_customers", "gold_exchange_rates", "gold_transactions"
    ]
    for tbl in expected_tables:
        assert tbl in tables, f"Expected table '{tbl}' not found in lakehouse.duckdb"

def test_primary_keys_uniqueness_and_not_null(con):
    pk_checks = [
        ("silver_customers", "customer_id"),
        ("silver_products", "product_id"),
        ("silver_transactions", "transaction_id"),
        ("silver_complaints", "complaint_id"),
        ("gold_customers", "customer_id"),
        ("gold_transactions", "transaction_id"),
    ]
    for table, pk in pk_checks:
        total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        distinct = con.execute(f"SELECT COUNT(DISTINCT {pk}) FROM {table}").fetchone()[0]
        nulls = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {pk} IS NULL").fetchone()[0]
        assert total > 0, f"Table {table} is empty"
        assert total == distinct, f"Duplicate PKs found in {table}.{pk} ({total} rows, {distinct} distinct)"
        assert nulls == 0, f"Null PKs found in {table}.{pk}"

def test_foreign_key_referential_integrity(con):
    # Transactions must belong to known customers in the sample
    orphan_trx_cust = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        LEFT JOIN silver_customers c ON t.customer_id = c.customer_id
        WHERE c.customer_id IS NULL;
    """).fetchone()[0]
    assert orphan_trx_cust == 0, f"Found {orphan_trx_cust} transactions with orphaned customer_id"

    # Transactions must belong to known products
    orphan_trx_prod = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        LEFT JOIN silver_products p ON t.product_id = p.product_id
        WHERE p.product_id IS NULL;
    """).fetchone()[0]
    assert orphan_trx_prod == 0, f"Found {orphan_trx_prod} transactions with orphaned product_id"

    # Products must belong to known customers
    orphan_prod_cust = con.execute("""
        SELECT COUNT(*) FROM silver_products p
        LEFT JOIN silver_customers c ON p.customer_id = c.customer_id
        WHERE c.customer_id IS NULL;
    """).fetchone()[0]
    assert orphan_prod_cust == 0, f"Found {orphan_prod_cust} products with orphaned customer_id"

    # Transaction customer must match product customer
    mismatch_cust = con.execute("""
        SELECT COUNT(*) FROM silver_transactions t
        JOIN silver_products p ON t.product_id = p.product_id
        WHERE t.customer_id != p.customer_id;
    """).fetchone()[0]
    assert mismatch_cust == 0, f"Found {mismatch_cust} transactions where customer != product owner"

def test_gold_transactions_date_window_consistency(con):
    # Ensure no future dated transactions relative to processing date
    future_trx = con.execute("""
        SELECT COUNT(*) FROM gold_transactions WHERE days_since_transaction < 0;
    """).fetchone()[0]
    assert future_trx == 0, f"Found {future_trx} transactions with negative days_since_transaction"

    # For the June 2026 slice, all transactions must fall within the 60-day policy window
    non_window_trx = con.execute("""
        SELECT COUNT(*) FROM gold_transactions WHERE NOT is_within_60_days;
    """).fetchone()[0]
    assert non_window_trx == 0, f"Found {non_window_trx} transactions outside 60d window in June 2026 slice"

def test_gold_transactions_currency_normalization(con):
    # All normalized amounts must be populated and positive
    bad_amounts = con.execute("""
        SELECT COUNT(*) FROM gold_transactions 
        WHERE amount_usd IS NULL OR amount_usd <= 0;
    """).fetchone()[0]
    assert bad_amounts == 0, f"Found {bad_amounts} transactions with invalid normalized USD amounts"

    # USD transactions must equal amount_usd exactly
    usd_diff = con.execute("""
        SELECT COUNT(*) FROM gold_transactions
        WHERE currency = 'USD' AND amount != amount_usd;
    """).fetchone()[0]
    assert usd_diff == 0, f"Found {usd_diff} USD transactions where amount != normalized amount"

def test_gold_customers_profile_integrity(con):
    # account_age_days must be non-negative
    neg_age = con.execute("""
        SELECT COUNT(*) FROM gold_customers WHERE account_age_days < 0;
    """).fetchone()[0]
    assert neg_age == 0, f"Found {neg_age} customers with negative account_age_days"

    # complaints_last_90d must be non-negative
    neg_complaints = con.execute("""
        SELECT COUNT(*) FROM gold_customers WHERE complaints_last_90d < 0;
    """).fetchone()[0]
    assert neg_complaints == 0, f"Found {neg_complaints} customers with negative complaints_last_90d"
