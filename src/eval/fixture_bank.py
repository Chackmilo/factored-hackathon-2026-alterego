"""Build a small DuckDB bank (lakehouse schemas) from case data, so a case carries its own system of record."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

BANK_SCHEMAS = {
    "silver_products": """CREATE TABLE silver_products (
        product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, product_number VARCHAR, currency VARCHAR,
        current_balance DOUBLE, credit_limit DOUBLE, interest_rate DOUBLE, opening_date DATE, expiration_date DATE,
        opening_branch_id VARCHAR, product_status VARCHAR, opening_channel VARCHAR, has_linked_app BOOLEAN,
        days_past_due DOUBLE, last_transaction_date TIMESTAMP, last_updated TIMESTAMP)""",
    "silver_transactions": """CREATE TABLE silver_transactions (
        transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, product_id VARCHAR, customer_id VARCHAR,
        transaction_type VARCHAR, transaction_category VARCHAR, amount DOUBLE, currency VARCHAR, amount_usd DOUBLE,
        channel VARCHAR, branch_id VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR, transaction_country VARCHAR,
        transaction_city VARCHAR, transaction_status VARCHAR, response_code VARCHAR, is_fraud BOOLEAN, fraud_score DOUBLE,
        latitude DOUBLE, longitude DOUBLE, day VARCHAR, month VARCHAR, year BIGINT)""",
    "silver_complaints": """CREATE TABLE silver_complaints (
        complaint_id VARCHAR, creation_date TIMESTAMP, process_date DATE, customer_id VARCHAR, case_type VARCHAR,
        category VARCHAR, subcategory VARCHAR, reception_channel VARCHAR, affected_product_id VARCHAR,
        related_branch_id VARCHAR, origin_interaction_id VARCHAR, description VARCHAR, claimed_amount DOUBLE,
        currency VARCHAR, priority VARCHAR, status VARCHAR, assigned_agent_id VARCHAR, assignment_date TIMESTAMP,
        first_response_date TIMESTAMP, resolution_date TIMESTAMP, closing_date TIMESTAMP, sla_breached BOOLEAN,
        resolution_days DOUBLE, resolution VARCHAR, compensation_granted DOUBLE, resolution_satisfaction DOUBLE,
        is_repeat_complainer BOOLEAN, day VARCHAR, month VARCHAR, year BIGINT)""",
    "gold_customers": """CREATE TABLE gold_customers (
        customer_id VARCHAR, document_number VARCHAR, document_type VARCHAR, first_name VARCHAR, last_name VARCHAR,
        full_name VARCHAR, email VARCHAR, mobile_phone VARCHAR, country VARCHAR, city VARCHAR, segment VARCHAR,
        credit_score DOUBLE, registration_date TIMESTAMP, customer_status VARCHAR, accepts_marketing BOOLEAN,
        account_age_days BIGINT, is_account_mature BOOLEAN, complaints_last_90d BIGINT, active_products BIGINT)""",
    "gold_transactions": """CREATE TABLE gold_transactions (
        transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, customer_id VARCHAR, product_id VARCHAR,
        product_type VARCHAR, product_status VARCHAR, transaction_type VARCHAR, amount DOUBLE, currency VARCHAR,
        amount_usd DOUBLE, amount_usd_source VARCHAR, channel VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR,
        transaction_country VARCHAR, transaction_city VARCHAR, transaction_status VARCHAR, is_fraud BOOLEAN,
        fraud_score DOUBLE, is_within_60_days BOOLEAN, days_since_transaction BIGINT)""",
}

ANCHOR = "2026-06-17"


def build_bank_fixture(path: str | Path, customers: list[dict[str, Any]], cards: list[dict[str, Any]],
                       transactions: list[dict[str, Any]]) -> str:
    """Create the bank file. Transactions carry process_date; transaction_date defaults to process day 12:00 UTC."""
    path = Path(path)
    if path.exists():
        path.unlink()
    con = duckdb.connect(str(path))
    try:
        for ddl in BANK_SCHEMAS.values():
            con.execute(ddl)
        for c in customers:
            con.execute("""INSERT INTO gold_customers (customer_id, full_name, email, country, city, segment, account_age_days,
                is_account_mature, complaints_last_90d, active_products) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [c["customer_id"], c.get("full_name", "Eval Customer"), None, c["country"], c.get("city"), c["segment"],
                         int(c["account_age_days"]), int(c["account_age_days"]) > 180, int(c.get("complaints_last_90d", 0)), len(cards)])
        for card in cards:
            con.execute("INSERT INTO silver_products (product_id, customer_id, product_type, product_status, currency) VALUES (?, ?, ?, ?, ?)",
                        [card["product_id"], card["customer_id"], card.get("product_type", "Tarjeta Crédito"), card.get("product_status", "Active"),
                         card.get("currency")])
        for t in transactions:
            process_date = t["process_date"]
            tx_date = t.get("transaction_date", f"{process_date} 12:00:00")
            amount_usd = t.get("amount_usd", t["amount"] if t.get("currency", "USD") == "USD" else None)
            days = (_date(ANCHOR) - _date(process_date)).days
            con.execute("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id,
                product_type, product_status, transaction_type, amount, currency, amount_usd, amount_usd_source, merchant_name,
                merchant_category, transaction_status, is_within_60_days, days_since_transaction, channel, transaction_country, transaction_city)
                VALUES (?, ?, ?, ?, ?, 'Tarjeta Crédito', 'Active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [t["transaction_id"], tx_date, process_date, t["customer_id"], t.get("product_id"), t.get("transaction_type", "Purchase"),
                         float(t["amount"]), t.get("currency", "USD"), amount_usd, t.get("amount_usd_source", "same_currency" if t.get("currency", "USD") == "USD" else "native"), t.get("merchant_name"),
                         t.get("merchant_category"), t.get("transaction_status", "Approved"), 0 <= days <= 60, days,
                         t.get("channel"), t.get("transaction_country"), t.get("transaction_city")])
            con.execute("""INSERT INTO silver_transactions (transaction_id, transaction_date, process_date, product_id, customer_id,
                transaction_type, amount, currency, merchant_name, transaction_status, channel, transaction_country, transaction_city)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        [t["transaction_id"], tx_date, process_date, t.get("product_id"), t["customer_id"], t.get("transaction_type", "Purchase"),
                         float(t["amount"]), t.get("currency", "USD"), t.get("merchant_name"), t.get("transaction_status", "Approved"),
                         t.get("channel"), t.get("transaction_country"), t.get("transaction_city")])
    finally:
        con.close()
    return str(path)


def _date(value: str):
    from datetime import date
    return date.fromisoformat(value[:10])
