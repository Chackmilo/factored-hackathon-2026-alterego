"""
Publish the minimized serving subset from the DuckDB lakehouse (or a team fixture with the same schemas) to
the `bank` schema in Postgres (docs/SUPABASE_VERCEL.md section 4.3).

    uv run python -m src.data.publish_serving --database-url postgresql://... [--source data/lakehouse.duckdb]
                                              [--customers data/serving_customers.json]

Rules: normalize "Mexico" to "México"; keep transaction_date and process_date as the CSV has them; keep the
native amount_usd, copy the amount for USD rows, fill COP and ARS gaps from the daily rate of the process day
and fail when no rate exists (never a 1.0 fallback); quarantine orphans before loading; reload bank in one
transaction; then check parity of counts, forbidden columns, and max(process_date) <= today. Never touches ops.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

BUSINESS_TODAY = date(2026, 6, 17)
FORBIDDEN_COLUMNS = {"is_fraud", "fraud_score", "document_number", "document_type", "email", "mobile_phone", "product_number",
                     "credit_score", "current_balance", "credit_limit", "description", "resolution", "affected_product_id"}
COUNTRY_FIX = {"Mexico": "México"}


class PublishError(RuntimeError):
    pass


def normalize_country(value: str | None) -> str | None:
    return COUNTRY_FIX.get(value, value) if value is not None else None


def fill_amount_usd(amount: float, currency: str, native_usd: float | None, rate: float | None) -> tuple[float, str]:
    """(amount_usd, source). Raises PublishError when a non-USD row has neither a native value nor a daily rate."""
    if currency == "USD":
        return float(amount), "same_currency"
    if native_usd is not None:
        return float(native_usd), "native"
    if rate is None:
        raise PublishError(f"No exchange rate for {currency} and no native amount_usd; refusing the 1.0 fallback")
    return round(float(amount) * float(rate), 2), "daily_rate_fill"


def _has_table(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [name]).fetchone()[0] > 0


def extract(source: str | Path, customer_ids: list[str] | None = None) -> dict[str, Any]:
    """Read the serving subset from DuckDB (read-only) and return rows per bank table plus the quarantine counts."""
    con = duckdb.connect(str(source), read_only=True)
    try:
        where = ""
        params: list[Any] = []
        if customer_ids:
            where = " WHERE customer_id IN (SELECT UNNEST(?::VARCHAR[]))"
            params = [customer_ids]
        customers = con.execute(f"""SELECT customer_id, full_name, country,
                {'city' if 'city' in _columns(con, 'gold_customers') else 'NULL'} AS city, segment,
                {'registration_date' if 'registration_date' in _columns(con, 'gold_customers') else 'NULL'} AS registration_date,
                {'customer_status' if 'customer_status' in _columns(con, 'gold_customers') else 'NULL'} AS customer_status,
                account_age_days FROM gold_customers{where}""", params).fetchall()
        customer_rows = []
        for cid, name, country, city, seg, reg, status, age in customers:
            if reg is None and age is not None:
                reg = BUSINESS_TODAY - timedelta(days=int(age))  # derived so the live view computes the same age
            customer_rows.append((cid, name, normalize_country(country), city, seg, reg, status))
        published = {r[0] for r in customer_rows}

        pcols = _columns(con, "silver_products")
        products = con.execute(f"""SELECT product_id, customer_id, product_type, product_status,
                {'currency' if 'currency' in pcols else 'NULL'}, {'opening_date' if 'opening_date' in pcols else 'NULL'},
                {'expiration_date' if 'expiration_date' in pcols else 'NULL'},
                {'RIGHT(product_number, 4)' if 'product_number' in pcols else 'NULL'} FROM silver_products""").fetchall()
        product_rows = [p for p in products if p[1] in published]
        product_ids = {p[0] for p in product_rows}
        quarantine = {"products_orphan_customer": len(products) - len(product_rows)}

        rates: dict[tuple[date, str], float] = {}
        if _has_table(con, "bronze_daily_exchange_rates"):
            for d, src, tgt, rate in con.execute("SELECT date, source_currency, target_currency, exchange_rate FROM bronze_daily_exchange_rates").fetchall():
                if tgt == "USD":
                    rates[(d if isinstance(d, date) else date.fromisoformat(str(d)[:10]), src)] = float(rate)

        tcols = _columns(con, "gold_transactions")
        transactions = con.execute(f"""SELECT transaction_id, customer_id, product_id, transaction_date, process_date, transaction_type,
                amount, currency, amount_usd, {'amount_usd_source' if 'amount_usd_source' in tcols else 'NULL'} AS amount_usd_source,
                {'channel' if 'channel' in tcols else 'NULL'}, merchant_name,
                {'merchant_category' if 'merchant_category' in tcols else 'NULL'}, {'transaction_country' if 'transaction_country' in tcols else 'NULL'},
                {'transaction_city' if 'transaction_city' in tcols else 'NULL'}, transaction_status FROM gold_transactions""").fetchall()
        transaction_rows, orphan_tx = [], 0
        for row in transactions:
            tid, cid, pid, tdate, pdate, ttype, amount, currency, native_usd, gold_source, channel, merchant, mcat, tcountry, tcity, status = row
            if cid not in published:
                orphan_tx += 1
                continue
            pday = pdate if isinstance(pdate, date) else date.fromisoformat(str(pdate)[:10])
            if gold_source and native_usd is not None:  # already fixed at silver (TQ-003): pass the value and its source through
                usd, source = float(native_usd), str(gold_source)
            else:
                usd, source = fill_amount_usd(float(amount), str(currency), native_usd, rates.get((pday, str(currency))))
            transaction_rows.append((tid, cid, pid if pid in product_ids else None, tdate, pday, ttype, float(amount), currency, usd, source,
                                     channel, merchant, mcat, normalize_country(tcountry), tcity, status))
        quarantine["transactions_orphan_customer"] = orphan_tx

        complaint_rows = []
        if _has_table(con, "silver_complaints"):
            ccols = _columns(con, "silver_complaints")
            complaints = con.execute(f"""SELECT complaint_id, customer_id, creation_date, process_date, case_type, category, subcategory, status,
                    claimed_amount, currency, {'is_repeat_complainer' if 'is_repeat_complainer' in ccols else 'NULL'} FROM silver_complaints""").fetchall()
            complaint_rows = [c for c in complaints if c[1] in published]
            quarantine["complaints_orphan_customer"] = len(complaints) - len(complaint_rows)

        rate_rows = [(d, s, t, r) for (d, s), r in rates.items() for t in ("USD",)]
        return {"customers": customer_rows, "products": product_rows, "transactions": transaction_rows, "complaints": complaint_rows,
                "exchange_rates": rate_rows, "quarantine": quarantine}
    finally:
        con.close()


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", [table]).fetchall()}


INSERTS = {
    "customers": ("INSERT INTO bank.customers (customer_id, full_name, country, city, segment, registration_date, customer_status) VALUES (%s, %s, %s, %s, %s, %s, %s)"),
    "products": ("INSERT INTO bank.products (product_id, customer_id, product_type, product_status, currency, opening_date, expiration_date, last4) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"),
    "transactions": ("INSERT INTO bank.transactions (transaction_id, customer_id, product_id, transaction_date, process_date, transaction_type, amount, currency, "
                     "amount_usd, amount_usd_source, channel, merchant_name, merchant_category, transaction_country, transaction_city, transaction_status) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"),
    "complaints": ("INSERT INTO bank.complaints (complaint_id, customer_id, creation_date, process_date, case_type, category, subcategory, status, claimed_amount, currency, is_repeat_complainer) "
                   "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"),
    "exchange_rates": ("INSERT INTO bank.exchange_rates (rate_date, source_currency, target_currency, exchange_rate) VALUES (%s, %s, %s, %s)"),
}


def load(database_url: str, subset: dict[str, Any]) -> dict[str, Any]:
    """Empty and reload bank in one transaction, then run the parity contracts. Returns the contract report."""
    import psycopg

    with psycopg.connect(database_url) as con:
        with con.cursor() as cur:
            cur.execute("TRUNCATE bank.transactions, bank.complaints, bank.products, bank.customers, bank.exchange_rates")
            for table in ("customers", "products", "transactions", "complaints", "exchange_rates"):
                if subset[table]:
                    cur.executemany(INSERTS[table], subset[table])
        con.commit()
        return contracts(con, subset)


def contracts(con, subset: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {"counts": {}, "forbidden_columns": [], "max_process_date_ok": True, "quarantine": subset["quarantine"]}
    with con.cursor() as cur:
        for table in ("customers", "products", "transactions", "complaints", "exchange_rates"):
            cur.execute(f"SELECT COUNT(*) FROM bank.{table}")
            got = cur.fetchone()[0]
            report["counts"][table] = {"source": len(subset[table]), "bank": got, "parity": got == len(subset[table])}
        cur.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'bank'")
        report["forbidden_columns"] = [f"{t}.{c}" for t, c in cur.fetchall() if c in FORBIDDEN_COLUMNS]
        cur.execute("SELECT COALESCE(MAX(process_date), DATE '2000-01-01') FROM bank.transactions")
        report["max_process_date_ok"] = cur.fetchone()[0] <= BUSINESS_TODAY
    report["ok"] = all(v["parity"] for v in report["counts"].values()) and not report["forbidden_columns"] and report["max_process_date_ok"]
    return report


def publish(database_url: str, source: str | Path = "data/lakehouse.duckdb", customers_path: str | Path | None = None) -> dict[str, Any]:
    customer_ids = None
    if customers_path:
        payload = json.loads(Path(customers_path).read_text())
        customer_ids = payload["customer_ids"] if isinstance(payload, dict) else list(payload)
    subset = extract(source, customer_ids)
    report = load(database_url, subset)
    if not report["ok"]:
        raise PublishError(f"Serving contracts failed: {report}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the minimized serving subset to the bank schema.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source", default="data/lakehouse.duckdb", help="DuckDB lakehouse or a team fixture with the same schemas")
    parser.add_argument("--customers", default=None, help="JSON with customer_ids to publish (team-generated list); default: all")
    args = parser.parse_args()
    report = publish(args.database_url, args.source, args.customers)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
