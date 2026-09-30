"""
Bank rows to the canonical frame of the feature contract: the lakehouse for calibration, the gateway rows for serving.

Only columns the serving copy holds (supabase/migrations/0003_bank.sql) are used: transactions (time, amounts, channel,
country, city), products (type, currency, opening date) and customers (country, city). The processing clock is
transaction_date minus 6 h (AGENTS.md section 7).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

CARD_KIND = {"Tarjeta Crédito": "credit", "Tarjeta Débito": "debit"}
COUNTRY_CURRENCY = {"México": "MXN", "Mexico": "MXN", "Colombia": "COP", "Argentina": "ARS"}


def _norm(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v).replace("Mexico", "México").strip().lower()


def address_bucket(tx_country: Any, tx_city: Any, home_country: Any, home_city: Any) -> float:
    tc, hc = _norm(tx_country), _norm(home_country)
    if tc is None or hc is None:
        return np.nan
    if tc != hc:
        return 2.0
    tcity, hcity = _norm(tx_city), _norm(home_city)
    return 1.0 if (tcity is not None and hcity is not None and tcity != hcity) else 0.0


def consistency(tx_country: Any, tx_city: Any, currency: Any, home_country: Any, home_city: Any, product_currency: Any) -> float:
    checks = []
    tc, hc = _norm(tx_country), _norm(home_country)
    if tc is not None and hc is not None:
        checks.append(float(tc == hc))
        expected = COUNTRY_CURRENCY.get(str(tx_country).replace("Mexico", "México"))
        if expected is not None and currency is not None:
            checks.append(float(str(currency) == expected))
    tcity, hcity = _norm(tx_city), _norm(home_city)
    if tcity is not None and hcity is not None:
        checks.append(float(tcity == hcity))
    if currency is not None and product_currency is not None and not (isinstance(product_currency, float) and np.isnan(product_currency)):
        checks.append(float(str(currency) == str(product_currency)))
    return float(np.mean(checks)) if checks else np.nan


def load_bank_canonical(lakehouse: str | Path, channels: tuple[str, ...] = ("Web", "App"), window_days: int = 60,
                        lookback_days: int = 30) -> pd.DataFrame:
    """Charges of the serving window plus the lookback the aggregates need; `in_scope` marks the window rows on the served channels."""
    con = duckdb.connect(str(lakehouse), read_only=True)
    try:
        anchor = con.execute("SELECT max(process_date) FROM silver_transactions").fetchone()[0]
        since = anchor - timedelta(days=window_days + lookback_days)
        window_from = anchor - timedelta(days=window_days)
        df = con.execute("""
            SELECT t.transaction_id AS row_id, t.product_id AS uid, t.customer_id AS customer_uid,
                   t.transaction_date - INTERVAL 6 HOUR AS ts, t.process_date, t.channel, t.amount_usd, t.amount AS amount_local, t.currency,
                   t.transaction_country, t.transaction_city, p.product_type, p.currency AS product_currency,
                   CASE WHEN p.opening_date IS NULL THEN NULL ELSE greatest(0, datediff('day', p.opening_date, t.process_date)) END AS card_age_days,
                   c.country AS home_country, c.city AS home_city, COALESCE(t.is_fraud, false)::INT AS label
            FROM silver_transactions t
            LEFT JOIN silver_products p ON p.product_id = t.product_id
            LEFT JOIN gold_customers c ON c.customer_id = t.customer_id
            WHERE t.process_date >= ?""", [since]).df()
    finally:
        con.close()
    df["card_kind"] = df["product_type"].map(CARD_KIND).where(df["product_type"].isin(CARD_KIND), "account")
    df["address_distance_bucket"] = [address_bucket(a, b, c, d) for a, b, c, d in zip(df.transaction_country, df.transaction_city, df.home_country, df.home_city)]
    df["consistency_matches"] = [consistency(a, b, cur, c, d, pc) for a, b, cur, c, d, pc in
                                 zip(df.transaction_country, df.transaction_city, df.currency, df.home_country, df.home_city, df.product_currency)]
    df["in_scope"] = (pd.to_datetime(df["process_date"]).dt.date >= window_from) & df["channel"].isin(list(channels))
    df.attrs["anchor"] = str(anchor)
    return df


def rows_to_canonical(matched: dict[str, Any], history: list[dict[str, Any]], profile: dict[str, Any]) -> pd.DataFrame:
    """Gateway rows (search_customer_transactions) plus the profile, for the scorer. Card age is not deployable and stays null."""
    rows = [r for r in history if r.get("transaction_id") != matched.get("transaction_id")] + [matched]
    out = []
    for r in rows:
        ts = pd.to_datetime(r.get("transaction_date")) - timedelta(hours=6)
        ptype = r.get("product_type")
        out.append({
            "row_id": r.get("transaction_id"), "uid": r.get("product_id") or "card", "customer_uid": r.get("customer_id") or "current", "ts": ts,
            "amount_usd": r.get("amount_usd"), "amount_local": r.get("amount"),  # a NULL stays NULL and scores as 0.0, as in training
            "card_kind": CARD_KIND.get(ptype, "account") if ptype else None, "card_age_days": np.nan,
            "address_distance_bucket": address_bucket(r.get("transaction_country"), r.get("transaction_city"), profile.get("country"), profile.get("city")),
            "consistency_matches": consistency(r.get("transaction_country"), r.get("transaction_city"), r.get("currency"), profile.get("country"),
                                               profile.get("city"), r.get("product_currency")),
        })
    return pd.DataFrame(out)
