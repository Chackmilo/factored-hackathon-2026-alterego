"""
Banking tool gateway on Supabase Postgres: reads the read-only `bank` serving copy and the live `ops` views,
and writes the card lock into `ops.card_locks` (never into `bank.products`), reading the effective status back
from `ops.v_product_status`. Same interface as BankingToolGateway (DuckDB), same authorization rule: every read
is filtered by the session's customer_id, every mutation checks ownership first.
"""
from __future__ import annotations

import html
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

import psycopg

from src.auth.session import VerifiedSession
from src.tools.gateway import (
    ActionVerificationError,
    RecordNotFoundError,
    SystemOfRecordUnavailableError,
    UnauthorizedAccessError,
    check_lock_reason,
    check_lockable,
)

BUSINESS_TODAY = date(2026, 6, 17)


class PostgresBankingGateway:
    def __init__(self, database_url: str):
        self.database_url = database_url

    @contextmanager
    def _con(self):
        try:
            # prepare_threshold=None: Supabase's transaction-mode pooler (Vercel, port 6543) cannot run prepared statements
            with psycopg.connect(self.database_url, autocommit=True, connect_timeout=5, prepare_threshold=None) as con:
                yield con
        except psycopg.OperationalError as exc:  # unreachable or dropped connection, connect timeout, a server-set statement timeout
            raise SystemOfRecordUnavailableError(str(exc)) from exc  # queries get no client-side timeout here (TQ-028)

    def search_customer_transactions(self, session: VerifiedSession, limit: int = 5, only_within_window: bool = False) -> list[dict[str, Any]]:
        window = "AND t.process_date BETWEEN ops.business_today() - 60 AND ops.business_today()" if only_within_window else ""
        with self._con() as con:
            rows = con.execute(f"""
                SELECT t.transaction_id, t.transaction_date, t.process_date, t.transaction_type, t.amount, t.currency, t.amount_usd,
                       t.product_id, p.product_type, s.product_status, t.channel, t.merchant_name, t.merchant_category, t.transaction_status,
                       (ops.business_today() - t.process_date) AS days_since_transaction, t.transaction_country, t.transaction_city,
                       p.currency AS product_currency
                FROM bank.transactions t
                LEFT JOIN bank.products p ON p.product_id = t.product_id
                LEFT JOIN ops.v_product_status s ON s.product_id = t.product_id
                WHERE t.customer_id = %s {window}
                ORDER BY t.transaction_date DESC LIMIT %s""", [session.customer_id, limit]).fetchall()
        out = []
        for r in rows:
            (tid, tdate, pdate, ttype, amount, currency, usd, pid, ptype, pstatus, channel, merchant, mcat, status, days, tcountry, tcity, pcurrency) = r
            raw_merchant = str(merchant or "Unknown")
            out.append({
                "transaction_id": tid, "transaction_date": tdate.isoformat() if isinstance(tdate, datetime) else str(tdate),
                "process_date": pdate.isoformat(), "transaction_type": ttype, "amount": float(amount), "currency": currency,
                "amount_usd": float(usd) if usd is not None else None, "product_id": pid, "product_type": ptype,
                "product_status": pstatus, "channel": channel, "merchant_name_raw": raw_merchant,
                "merchant_name": f"<untrusted_merchant_data>{html.escape(raw_merchant)}</untrusted_merchant_data>",
                "merchant_category": html.escape(str(mcat)) if mcat is not None else None, "transaction_status": status,
                "is_within_60_days": 0 <= int(days) <= 60, "days_since_transaction": int(days),
                "transaction_country": tcountry, "transaction_city": html.escape(str(tcity)) if tcity is not None else None,
                "product_currency": pcurrency,
            })
        return out

    def get_customer_profile(self, session: VerifiedSession) -> dict[str, Any]:
        with self._con() as con:
            row = con.execute("""SELECT f.customer_id, f.full_name, f.country, f.segment, f.account_age_days, f.is_account_mature, f.complaints_last_90d,
                                        f.active_products, (SELECT c.city FROM bank.customers c WHERE c.customer_id = f.customer_id)
                                 FROM ops.v_customer_policy_facts f WHERE f.customer_id = %s""", [session.customer_id]).fetchone()
        if not row:
            raise RecordNotFoundError(f"Customer {session.customer_id} not found in system of record.")
        keys = ["customer_id", "full_name", "country", "segment", "account_age_days", "is_account_mature", "complaints_last_90d", "active_products", "city"]
        profile = dict(zip(keys, row))
        profile["complaints_include_ops_cases"] = True  # the live view already counts the system's own cases
        return profile

    def list_customer_cards(self, session: VerifiedSession, only_active: bool = True) -> list[dict[str, Any]]:
        status = "AND product_status = 'Active'" if only_active else ""
        with self._con() as con:
            rows = con.execute(f"""SELECT product_id, product_type, product_status FROM ops.v_product_status
                                   WHERE customer_id = %s AND product_type LIKE 'Tarjeta%%' {status} ORDER BY product_id""", [session.customer_id]).fetchall()
        return [{"product_id": r[0], "product_type": r[1], "product_status": r[2]} for r in rows]

    def get_customer_identity(self, customer_id: str) -> dict[str, Any] | None:
        with self._con() as con:
            row = con.execute("SELECT customer_id, full_name, country, segment FROM bank.customers WHERE customer_id = %s", [customer_id]).fetchone()
        return {"customer_id": row[0], "name": row[1], "country": row[2], "segment": row[3]} if row else None

    def sample_customers(self, limit: int = 6) -> list[dict[str, Any]]:
        with self._con() as con:
            rows = con.execute("""SELECT f.customer_id, f.segment, f.country, f.account_age_days, f.complaints_last_90d
                                  FROM ops.v_customer_policy_facts f
                                  WHERE EXISTS (SELECT 1 FROM bank.transactions t WHERE t.customer_id = f.customer_id)
                                  ORDER BY f.customer_id LIMIT %s""", [limit]).fetchall()
        return [{"customer_id": r[0], "segment": r[1], "country": r[2], "account_age_days": int(r[3]), "complaints_last_90d": int(r[4])} for r in rows]

    def execute_lock_card(self, session: VerifiedSession, product_id: str, reason: str = "Preventive security hold for dispute",
                          lock_id: str | None = None, reason_code: str = "STOLEN_CARD_CLAIM") -> dict[str, Any]:
        """Act: mark the offered lock as locked and verified in ops.card_locks (or insert one). Verify: read the effective status back."""
        check_lock_reason(reason_code)
        with self._con() as con:
            owner = con.execute("SELECT customer_id, product_type, product_status FROM ops.v_product_status WHERE product_id = %s",
                                [product_id]).fetchone()
            if not owner:
                raise ActionVerificationError(f"Product {product_id} not found in system of record.")
            if owner[0] != session.customer_id:
                raise UnauthorizedAccessError(f"Cross-customer violation: Product {product_id} does not belong to authenticated customer {session.customer_id}.")
            check_lockable(product_id, owner[1], owner[2])  # live status: a card our own lock blocked is not locked twice
            updated = 0
            if lock_id:
                updated = con.execute("""UPDATE ops.card_locks SET status = 'locked', verified = TRUE, updated_at = now()
                                         WHERE lock_id = %s AND customer_id = %s AND product_id = %s""", [lock_id, session.customer_id, product_id]).rowcount
            if not updated:
                lock_id = f"LOCK-{uuid.uuid4().hex[:12].upper()}"
                con.execute("""INSERT INTO ops.card_locks (lock_id, conversation_id, customer_id, product_id, reason, status, verified, created_at, updated_at)
                               VALUES (%s, NULL, %s, %s, %s, 'locked', TRUE, now(), now())""", [lock_id, session.customer_id, product_id, reason_code])
            verified = con.execute("SELECT product_status, active_lock_id FROM ops.v_product_status WHERE product_id = %s", [product_id]).fetchone()
        if not verified or verified[0] != "Blocked":
            raise ActionVerificationError(f"Verification failed: Product {product_id} status could not be verified as Blocked.")
        return {"verified": True, "action": "LOCK_CARD", "product_id": product_id, "status": verified[0], "lock_id": verified[1],
                "reason": reason, "timestamp": datetime.utcnow().isoformat()}
