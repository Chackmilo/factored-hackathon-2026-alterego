"""
Tests for which S3 partitions the ingestion pipeline reads, against a local copy of the partition layout.
"""
import duckdb
import pytest

from src.data.ingestion import (
    IngestionContractError,
    build_gold_transactions,
    build_silver_transactions,
    ingest_transactions_chunked,
    transaction_month_globs,
    transactions_glob,
)

PARTITIONS = [
    "year=2023/month=07/day=01",
    "year=2025/month=01/day=15",
    "year=2026/month=05/day=02",
    "year=2026/month=06/day=10",
]


@pytest.fixture
def partition_root(tmp_path):
    """Team-generated fixture: one empty CSV per daily partition, laid out like s3://<bucket>/data."""
    for partition in PARTITIONS:
        folder = tmp_path / "transactions" / partition
        folder.mkdir(parents=True)
        (folder / "part.csv").write_text("transaction_id\n")
    return tmp_path.as_posix()


def _matched_partitions(pattern: str) -> set:
    files = duckdb.sql(f"SELECT file FROM glob('{pattern}')").fetchall()
    return {"/".join(f.replace("\\", "/").split("/")[-4:-1]) for (f,) in files}


def test_full_load_reads_every_year(partition_root):
    """ML trains on 2023 to 2026, so sample_only=False must read every year's partitions."""
    assert _matched_partitions(transactions_glob(partition_root, sample_only=False)) == set(PARTITIONS)


def test_sample_reads_only_june_2026(partition_root):
    assert _matched_partitions(transactions_glob(partition_root, sample_only=True)) == {"year=2026/month=06/day=10"}


@pytest.fixture
def bronze_db(tmp_path):
    """Team-generated bronze fixture: USD, native COP, a COP gap with a rate, and an ARS gap without one (added per test)."""
    con = duckdb.connect(str(tmp_path / "bronze.duckdb"))
    con.execute("""CREATE TABLE bronze_transactions (transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, product_id VARCHAR,
        customer_id VARCHAR, transaction_type VARCHAR, amount DOUBLE, currency VARCHAR, amount_usd DOUBLE, channel VARCHAR, merchant_name VARCHAR,
        merchant_category VARCHAR, transaction_country VARCHAR, transaction_city VARCHAR, transaction_status VARCHAR, is_fraud BOOLEAN, fraud_score DOUBLE)""")
    con.execute("""INSERT INTO bronze_transactions (transaction_id, transaction_date, process_date, product_id, customer_id, transaction_type, amount, currency, amount_usd, merchant_name, transaction_status) VALUES
        ('T-USD', TIMESTAMP '2026-06-10 12:00:00', DATE '2026-06-10', 'P1', 'C1', 'Purchase', 80.0, 'USD', NULL, 'Oxxo', 'Approved'),
        ('T-COP-NATIVE', TIMESTAMP '2026-06-10 12:00:00', DATE '2026-06-10', 'P1', 'C1', 'Purchase', 324599.21, 'COP', 81.15, 'Cine', 'Approved'),
        ('T-COP-GAP', TIMESTAMP '2026-06-11 12:00:00', DATE '2026-06-11', 'P1', 'C1', 'Purchase', 608000.0, 'COP', NULL, 'Cine', 'Approved'),
        ('T-COP-GAP', TIMESTAMP '2026-06-11 12:00:00', DATE '2026-06-11', 'P1', 'C1', 'Purchase', 608000.0, 'COP', NULL, 'Cine', 'Approved')""")
    con.execute("CREATE TABLE bronze_daily_exchange_rates (date DATE, source_currency VARCHAR, target_currency VARCHAR, exchange_rate DOUBLE, buy_rate DOUBLE, sell_rate DOUBLE, source VARCHAR)")
    con.execute("INSERT INTO bronze_daily_exchange_rates VALUES (DATE '2026-06-11', 'COP', 'USD', 0.000248, 0.00024, 0.00025, 'Central Bank')")
    con.execute("CREATE TABLE silver_products (product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, product_status VARCHAR)")
    con.execute("INSERT INTO silver_products VALUES ('P1', 'C1', 'Tarjeta Crédito', 'Active')")
    return con


def test_silver_fixes_amount_usd_and_keeps_the_legacy_value(bronze_db):
    build_silver_transactions(bronze_db)
    rows = {r[0]: r for r in bronze_db.execute("SELECT transaction_id, amount_usd, amount_usd_legacy, amount_usd_source, amount_usd_fx_rate FROM silver_transactions").fetchall()}
    assert len(rows) == 3  # the duplicate COP gap row is deduplicated on the business key
    assert rows["T-USD"][1:] == (80.0, None, "same_currency", None)
    assert rows["T-COP-NATIVE"][1:] == (81.15, 81.15, "native", None)
    assert rows["T-COP-GAP"][1:] == (150.78, None, "daily_rate_fill", 0.000248)


def test_silver_fails_the_load_when_a_gap_has_no_rate(bronze_db):
    bronze_db.execute("""INSERT INTO bronze_transactions (transaction_id, transaction_date, process_date, product_id, customer_id, transaction_type, amount, currency, amount_usd, transaction_status)
        VALUES ('T-ARS-NORATE', TIMESTAMP '2026-06-12 12:00:00', DATE '2026-06-12', 'P1', 'C1', 'Purchase', 1000.0, 'ARS', NULL, 'Approved')""")
    with pytest.raises(IngestionContractError):
        build_silver_transactions(bronze_db)


def test_gold_carries_the_fixed_amount_and_its_source_only(bronze_db):
    build_silver_transactions(bronze_db)
    build_gold_transactions(bronze_db, "2026-06-17")
    cols = {r[0] for r in bronze_db.execute("DESCRIBE gold_transactions").fetchall()}
    assert {"amount_usd", "amount_usd_source", "is_within_60_days", "days_since_transaction"} <= cols
    assert "amount_usd_normalized" not in cols and "amount_usd_legacy" not in cols and "amount_usd_fx_rate" not in cols
    assert bronze_db.execute("SELECT amount_usd, amount_usd_source, days_since_transaction FROM gold_transactions WHERE transaction_id = 'T-COP-GAP'").fetchone() == (150.78, "daily_rate_fill", 6)


def test_gold_tells_a_merchant_that_does_not_apply_from_one_that_is_missing(bronze_db):
    """Five charge types never carry a merchant in the dataset (the field does not apply); a purchase without one is a gap."""
    bronze_db.execute("""INSERT INTO bronze_transactions (transaction_id, transaction_date, process_date, product_id, customer_id, transaction_type, amount, currency, amount_usd, merchant_name, transaction_status) VALUES
        ('T-PURCHASE-GAP', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Purchase', 10.0, 'USD', NULL, NULL, 'Approved'),
        ('T-WITHDRAWAL', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Withdrawal', 11.0, 'USD', NULL, NULL, 'Approved'),
        ('T-TRANSFER', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Transfer', 12.0, 'USD', NULL, NULL, 'Approved'),
        ('T-PAYMENT', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Payment', 13.0, 'USD', NULL, NULL, 'Approved'),
        ('T-DEPOSIT', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Deposit', 14.0, 'USD', NULL, NULL, 'Approved'),
        ('T-ADJUSTMENT', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Adjustment', 15.0, 'USD', NULL, NULL, 'Approved'),
        ('T-TRANSFER-NAMED', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Transfer', 16.0, 'USD', NULL, 'Tienda Este', 'Approved'),
        ('T-NEW-TYPE', TIMESTAMP '2026-06-12 09:00:00', DATE '2026-06-12', 'P1', 'C1', 'Refund', 17.0, 'USD', NULL, NULL, 'Approved')""")
    build_silver_transactions(bronze_db)
    build_gold_transactions(bronze_db, "2026-06-17")
    labels = dict(bronze_db.execute("SELECT transaction_id, merchant_name FROM gold_transactions").fetchall())
    assert {labels[t] for t in ("T-WITHDRAWAL", "T-TRANSFER", "T-PAYMENT", "T-DEPOSIT", "T-ADJUSTMENT")} == {"Not Applicable"}
    assert labels["T-PURCHASE-GAP"] == "Unknown Merchant"
    assert labels["T-USD"] == "Oxxo" and labels["T-TRANSFER-NAMED"] == "Tienda Este"  # a name is never replaced
    assert labels["T-NEW-TYPE"] == "Unknown Merchant"  # a type the dataset does not have is not declared merchant-free


def test_month_globs_cover_the_dataset_period():
    globs = transaction_month_globs("s3://b/data")
    assert len(globs) == 37  # 2023-06 to 2026-06
    assert globs[0].endswith("year=2023/month=06/*/*.csv") and globs[-1].endswith("year=2026/month=06/*/*.csv")


def test_chunked_load_retries_a_failing_chunk_and_skips_empty_months(partition_root, monkeypatch):
    """A transient IO error on one month is retried; a month without partitions is skipped; the rest still loads."""
    con = duckdb.connect()
    for partition in ("year=2026/month=05/day=02", "year=2026/month=06/day=10"):
        (tmp := __import__("pathlib").Path(partition_root) / "transactions" / partition / "part.csv").write_text("transaction_id,amount\nT1,1.0\n")
    patterns = transaction_month_globs(partition_root, first=(2026, 4), last=(2026, 6))
    calls = {"n": 0}

    def flaky_execute(sql, *args, **kwargs):
        if "month=05" in sql and calls["n"] == 0:
            calls["n"] += 1
            raise duckdb.IOException("IO Error: Timeout was reached error for HTTP GET")
        return con.execute(sql, *args, **kwargs)

    slept = []
    loaded = ingest_transactions_chunked(con, patterns, retries=3, wait_seconds=0.01, sleep=slept.append, execute=flaky_execute)
    assert loaded == 2 and slept == [0.01]  # April has no files (skipped), May retried once, June loaded
    assert con.execute("SELECT COUNT(*) FROM bronze_transactions").fetchone()[0] == 2


def test_chunked_load_gives_up_after_the_retries(partition_root):
    con = duckdb.connect()

    def always_fails(sql, *args, **kwargs):
        if sql.startswith("DROP TABLE"):
            return con.execute(sql)
        raise duckdb.IOException("IO Error: Timeout")

    with pytest.raises(IngestionContractError):
        ingest_transactions_chunked(con, transaction_month_globs(partition_root, first=(2026, 6), last=(2026, 6)), retries=2, wait_seconds=0, sleep=lambda s: None, execute=always_fails)
