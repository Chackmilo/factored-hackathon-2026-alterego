"""
Tool Gateway with Act-and-Verify Execution Pattern and Zero-Trust Authorization.
Every tool enforces that customer_id matches the cryptographically verified session.
Mutating actions perform a round-trip database read-back before confirming success.
"""
import html
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from src.auth.session import VerifiedSession
from src.data.db import DEFAULT_DB_PATH, get_db_connection


class ActionVerificationError(Exception):
    """Raised when an action cannot be verified by reading back from the database."""
    pass

class UnauthorizedAccessError(Exception):
    """Raised when customer tries to access or alter records belonging to another customer."""
    pass

class RecordNotFoundError(Exception):
    """Raised when a record needed for a decision is missing from the system of record."""
    pass

class SystemOfRecordUnavailableError(Exception):
    """Raised when the system of record cannot be reached or does not answer in time; the outcome of a write is unknown."""
    pass

LOCK_REASON_CODES = ("STOLEN_CARD_CLAIM", "MULTI_CHARGE_FRAUD")  # the CHECK on ops.card_locks.reason (0001_ops.sql)


def check_lock_reason(code: str) -> str:
    """A card lock reason code the ops schema accepts, checked before any write."""
    if code not in LOCK_REASON_CODES:
        raise ValueError(f"Unknown card lock reason code {code!r}; expected one of {', '.join(LOCK_REASON_CODES)}.")
    return code

def _records(frame) -> list[dict[str, Any]]:
    """Rows with None for SQL NULL, as the Postgres gateway returns them: pandas reads NULL as NaN or NaT, and NaN passes `is not None`."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")

class BankingToolGateway:
    """
    Authorized Tool Gateway connecting to the DuckDB Lakehouse System of Record.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def _get_con(self):
        try:
            return get_db_connection(self.db_path, read_only=False)
        except duckdb.OperationalError as exc:  # IOException (another process holds the file lock), ConnectionException
            raise SystemOfRecordUnavailableError(str(exc)) from exc

    def search_customer_transactions(
        self,
        session: VerifiedSession,
        limit: int = 5,
        only_within_window: bool = False
    ) -> list[dict[str, Any]]:
        """
        Retrieves transactions strictly belonging to the authenticated customer.
        Indirect prompt injection defense: Merchant names are wrapped in untrusted data tags.
        """
        con = self._get_con()
        try:
            window_clause = "AND is_within_60_days = true" if only_within_window else ""
            query = f"""
                SELECT 
                    transaction_id,
                    transaction_date,
                    process_date,
                    transaction_type,
                    amount,
                    currency,
                    amount_usd,
                    product_id,
                    product_type,
                    channel,
                    merchant_name,
                    merchant_category,
                    transaction_status,
                    is_within_60_days,
                    days_since_transaction
                FROM gold_transactions
                WHERE customer_id = ? {window_clause}
                ORDER BY transaction_date DESC
                LIMIT ?;
            """
            rows = _records(con.execute(query, [session.customer_id, limit]).df())

            # Wrap merchant names in defensive XML boundaries
            for r in rows:
                raw_merchant = str(r.get("merchant_name") or "Unknown")
                r["merchant_name_raw"] = raw_merchant
                # SEC-04: escape every free-text field so a value cannot close the boundary tag
                r["merchant_name"] = f"<untrusted_merchant_data>{html.escape(raw_merchant)}</untrusted_merchant_data>"
                for free_text in ("merchant_category", "transaction_city"):
                    if r.get(free_text) is not None:
                        r[free_text] = html.escape(str(r[free_text]))
                if isinstance(r.get("transaction_date"), datetime):
                    r["transaction_date"] = r["transaction_date"].isoformat()
                if isinstance(r.get("process_date"), datetime):
                    r["process_date"] = r["process_date"].date().isoformat()

            return rows
        finally:
            con.close()

    def get_customer_profile(self, session: VerifiedSession) -> dict[str, Any]:
        """
        Retrieves enriched customer profile and dispute history.
        Raises RecordNotFoundError when the customer is missing: policy facts are never invented.
        """
        con = self._get_con()
        try:
            query = """
                SELECT 
                    customer_id,
                    full_name,
                    country,
                    segment,
                    account_age_days,
                    is_account_mature,
                    complaints_last_90d,
                    active_products
                FROM gold_customers
                WHERE customer_id = ?;
            """
            result = _records(con.execute(query, [session.customer_id]).df())
            if not result:
                raise RecordNotFoundError(
                    f"Customer {session.customer_id} not found in system of record."
                )
            return result[0]
        finally:
            con.close()

    def list_customer_cards(self, session: VerifiedSession, only_active: bool = True) -> list[dict[str, Any]]:
        """Card products of the authenticated customer (the only products a preventive lock may touch)."""
        con = self._get_con()
        try:
            status_clause = "AND product_status = 'Active'" if only_active else ""
            rows = con.execute(
                f"""SELECT product_id, product_type, product_status FROM silver_products
                    WHERE customer_id = ? AND product_type LIKE 'Tarjeta%' {status_clause} ORDER BY product_id""",
                [session.customer_id],
            ).fetchall()
            return [{"product_id": r[0], "product_type": r[1], "product_status": r[2]} for r in rows]
        finally:
            con.close()

    def get_customer_identity(self, customer_id: str) -> dict[str, Any] | None:
        """Minimal identity facts for the local test issuer (name, country, segment). No session: dev and test only."""
        con = self._get_con()
        try:
            row = con.execute(
                "SELECT customer_id, full_name, country, segment FROM gold_customers WHERE customer_id = ?", [customer_id]
            ).fetchone()
            if not row:
                return None
            return {"customer_id": row[0], "name": row[1], "country": row[2], "segment": row[3]}
        finally:
            con.close()

    def sample_customers(self, limit: int = 6) -> list[dict[str, Any]]:
        """A few customer ids with segment and country for the demo login page (no names, no contacts)."""
        con = self._get_con()
        try:
            rows = con.execute(
                """SELECT c.customer_id, c.segment, c.country, c.account_age_days, c.complaints_last_90d
                   FROM gold_customers c WHERE EXISTS (SELECT 1 FROM gold_transactions t WHERE t.customer_id = c.customer_id)
                   ORDER BY c.customer_id LIMIT ?""", [limit]
            ).fetchall()
            return [{"customer_id": r[0], "segment": r[1], "country": r[2], "account_age_days": int(r[3]),
                     "complaints_last_90d": int(r[4])} for r in rows]
        finally:
            con.close()

    def execute_lock_card(
        self,
        session: VerifiedSession,
        product_id: str,
        reason: str = "Preventive security hold for dispute",
        lock_id: str | None = None,  # used by the Postgres gateway; the DuckDB one writes silver_products
        reason_code: str = "STOLEN_CARD_CLAIM",
    ) -> dict[str, Any]:
        """
        Act & Verify: Locks customer card and reads back status to confirm.
        Enforces authorization: product must belong to session.customer_id.
        """
        check_lock_reason(reason_code)
        con = self._get_con()
        try:
            # 1. AUTHORIZATION CHECK
            owner_row = con.execute(
                "SELECT customer_id FROM silver_products WHERE product_id = ?",
                [product_id]
            ).fetchone()

            if not owner_row:
                raise ActionVerificationError(f"Product {product_id} not found in system of record.")

            if owner_row[0] != session.customer_id:
                raise UnauthorizedAccessError(
                    f"Cross-customer violation: Product {product_id} does not belong to authenticated customer {session.customer_id}."
                )

            # 2. ACT: Update product status in DB
            con.execute(
                "UPDATE silver_products SET product_status = 'Blocked' WHERE product_id = ?",
                [product_id]
            )

            # 3. VERIFY: Read back from DB
            verified_status = con.execute(
                "SELECT product_status FROM silver_products WHERE product_id = ?",
                [product_id]
            ).fetchone()

            if not verified_status or verified_status[0] != "Blocked":
                raise ActionVerificationError(
                    f"Verification failed: Product {product_id} status could not be verified as Blocked."
                )

            return {
                "verified": True,
                "action": "LOCK_CARD",
                "product_id": product_id,
                "status": verified_status[0],
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat()
            }
        finally:
            con.close()
