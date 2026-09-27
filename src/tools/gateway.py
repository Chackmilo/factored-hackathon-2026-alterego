"""
Tool Gateway with Act-and-Verify Execution Pattern and Zero-Trust Authorization.
Every tool enforces that customer_id matches the cryptographically verified session.
Mutating actions perform a round-trip database read-back before confirming success.
"""
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
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

class BankingToolGateway:
    """
    Authorized Tool Gateway connecting to the DuckDB Lakehouse System of Record.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH

    def _get_con(self):
        return get_db_connection(self.db_path, read_only=False)

    def search_customer_transactions(
        self,
        session: VerifiedSession,
        limit: int = 5,
        only_within_window: bool = False
    ) -> List[Dict[str, Any]]:
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
                    amount,
                    currency,
                    amount_usd_normalized,
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
            rows = con.execute(query, [session.customer_id, limit]).df().to_dict(orient="records")
            
            # Wrap merchant names in defensive XML boundaries
            for r in rows:
                raw_merchant = str(r.get("merchant_name") or "Unknown")
                r["merchant_name"] = f"<untrusted_merchant_data>{raw_merchant}</untrusted_merchant_data>"
                if isinstance(r.get("transaction_date"), datetime):
                    r["transaction_date"] = r["transaction_date"].isoformat()
                if isinstance(r.get("process_date"), datetime):
                    r["process_date"] = r["process_date"].date().isoformat()

            return rows
        finally:
            con.close()

    def get_customer_profile(self, session: VerifiedSession) -> Dict[str, Any]:
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
            result = con.execute(query, [session.customer_id]).df().to_dict(orient="records")
            if not result:
                raise RecordNotFoundError(
                    f"Customer {session.customer_id} not found in system of record."
                )
            return result[0]
        finally:
            con.close()

    def execute_lock_card(
        self,
        session: VerifiedSession,
        product_id: str,
        reason: str = "Preventive security hold for dispute"
    ) -> Dict[str, Any]:
        """
        Act & Verify: Locks customer card and reads back status to confirm.
        Enforces authorization: product must belong to session.customer_id.
        """
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

    def execute_open_dispute(
        self,
        session: VerifiedSession,
        transaction_id: str,
        dispute_reason: str,
        claimed_amount: float,
        currency: str
    ) -> Dict[str, Any]:
        """
        Act & Verify: Creates official dispute complaint ticket and reads back to verify.
        Enforces authorization: transaction must belong to session.customer_id.
        """
        con = self._get_con()
        try:
            # 1. AUTHORIZATION CHECK
            tx_row = con.execute(
                "SELECT customer_id, product_id FROM silver_transactions WHERE transaction_id = ?",
                [transaction_id]
            ).fetchone()

            if not tx_row:
                raise ActionVerificationError(f"Transaction {transaction_id} not found in system of record.")

            if tx_row[0] != session.customer_id:
                raise UnauthorizedAccessError(
                    f"Cross-customer violation: Transaction {transaction_id} does not belong to authenticated customer {session.customer_id}."
                )

            product_id = tx_row[1]
            complaint_id = f"CMP-AUTO-{uuid.uuid4().hex[:12].upper()}"
            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            # 2. ACT: Insert dispute into silver_complaints
            con.execute(
                """
                INSERT INTO silver_complaints (
                    complaint_id, creation_date, process_date, customer_id,
                    case_type, category, subcategory, reception_channel,
                    affected_product_id, description, claimed_amount,
                    currency, priority, status, sla_breached, is_repeat_complainer
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                [
                    complaint_id, now_str, now_str[:10], session.customer_id,
                    "Claim", "Fraud", "Cargo no reconocido", "Chat",
                    product_id, dispute_reason, claimed_amount,
                    currency, "High" if claimed_amount > 500 else "Medium",
                    "INTAKE_RECEIVED", False, False
                ]
            )

            # 3. VERIFY: Read back from DB
            persisted = con.execute(
                "SELECT complaint_id, status FROM silver_complaints WHERE complaint_id = ?",
                [complaint_id]
            ).fetchone()

            if not persisted or persisted[1] != "INTAKE_RECEIVED":
                raise ActionVerificationError(
                    f"Verification failed: Dispute case {complaint_id} could not be verified in system of record."
                )

            return {
                "verified": True,
                "action": "OPEN_DISPUTE",
                "case_id": complaint_id,
                "transaction_id": transaction_id,
                "status": persisted[1],
                "claimed_amount": claimed_amount,
                "currency": currency,
                "timestamp": now_str
            }
        finally:
            con.close()
