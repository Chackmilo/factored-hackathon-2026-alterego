"""
Shared pytest fixtures for OmniGuard AI / Dispute Intake test suite.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.auth.session import create_test_session
from src.rules.dispute_policy import DisputePolicyInput


@pytest.fixture(autouse=True)
def _mlflow_store_in_tmp(tmp_path_factory, monkeypatch):
    """Training runs track in MLflow (TQ-021); the suite keeps their SQLite store and artifacts out of the repo."""
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path_factory.mktemp('mlflow') / 'mlflow.db'}")


@pytest.fixture(scope="session")
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)

@pytest.fixture
def valid_session_token() -> str:
    """Generates a valid signed JWT test session token."""
    return create_test_session(
        customer_id="CLI-TEST-SHARED",
        name="Elena Rostova",
        country="Colombia",
        segment="Plus",
        ttl_seconds=3600,
    )

@pytest.fixture
def auth_headers(valid_session_token: str) -> dict:
    """HTTP Authorization header dict with valid Bearer token."""
    return {"Authorization": f"Bearer {valid_session_token}"}

@pytest.fixture
def sample_dispute_input() -> DisputePolicyInput:
    """Standard in-window dispute policy input fixture."""
    return DisputePolicyInput(
        customer_id="CLI-TEST-SHARED",
        customer_segment="Plus",
        customer_country="Colombia",
        account_age_days=250,
        complaints_last_90d=0,
        transaction_id="TRX-SHARED-001",
        transaction_date=date(2026, 6, 10),
        transaction_amount=120.0,
        transaction_currency="USD",
        amount_usd=120.0,
        transaction_type="Purchase",
        transaction_status="Approved",
        current_date=date(2026, 6, 17),
    )


# ---------------------------------------------------------------- dispute stack
import duckdb  # noqa: E402

from src.auth.session import VerifiedSession  # noqa: E402
from src.ops.store import OpsStore  # noqa: E402
from src.orchestrator.dispute_orchestrator import DisputeOrchestrator  # noqa: E402
from src.tools.gateway import BankingToolGateway  # noqa: E402

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

# Team-generated fixture rows (label: team-generated). Process day = date(transaction_date - 6 h).
BANK_TRANSACTIONS = [
    # id, transaction_date, process_date, customer, product, type, amount, currency, usd, merchant, status, in_window, days
    ("TRX-A-080", "2026-06-10 03:15:00", "2026-06-09", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 80.0, "USD", 80.0, "Oxxo", "Approved", True, 8),
    ("TRX-A-120", "2026-06-12 14:22:00", "2026-06-12", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 120.0, "USD", 120.0, "Cine Premium", "Approved", True, 5),
    ("TRX-A-850", "2026-06-14 20:05:00", "2026-06-14", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 850.0, "USD", 850.0, "Super Ahorro", "Approved", True, 3),
    ("TRX-A-DECL", "2026-06-15 10:00:00", "2026-06-15", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 45.0, "USD", 45.0, "Farmacia Central", "Declined", True, 2),
    ("TRX-A-OLD", "2026-03-19 12:00:00", "2026-03-19", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 60.0, "USD", 60.0, "Cine Premium", "Approved", False, 90),
    ("TRX-A-DUP1", "2026-06-11 09:00:00", "2026-06-11", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 35.0, "USD", 35.0, "Tienda Sur", "Approved", True, 6),
    ("TRX-A-DUP2", "2026-06-13 09:00:00", "2026-06-13", "CLI-FIX-OWNER", "PRD-CARD-1", "Purchase", 35.0, "USD", 35.0, "Tienda Norte", "Approved", True, 4),
    ("TRX-B-050", "2026-06-12 11:00:00", "2026-06-12", "CLI-FIX-OTHER", "PRD-CARD-2", "Purchase", 50.0, "USD", 50.0, "Oxxo", "Approved", True, 5),
]


@pytest.fixture
def bank_fixture_db(tmp_path):
    """Team-generated bank fixture with the lakehouse schemas: two customers, two cards, eight charges."""
    db_path = tmp_path / "bank_fixture.duckdb"
    con = duckdb.connect(str(db_path))
    for ddl in BANK_SCHEMAS.values():
        con.execute(ddl)
    con.execute("""INSERT INTO silver_products (product_id, customer_id, product_type, product_status) VALUES
        ('PRD-CARD-1', 'CLI-FIX-OWNER', 'Tarjeta Crédito', 'Active'),
        ('PRD-ACC-1', 'CLI-FIX-OWNER', 'Cuenta Ahorros', 'Active'),
        ('PRD-CARD-2', 'CLI-FIX-OTHER', 'Tarjeta Débito', 'Active')""")
    con.execute("""INSERT INTO gold_customers (customer_id, full_name, email, country, segment, account_age_days,
        is_account_mature, complaints_last_90d, active_products) VALUES
        ('CLI-FIX-OWNER', 'Ana Fixture', 'ana@example.test', 'Colombia', 'Plus', 250, true, 0, 2),
        ('CLI-FIX-OTHER', 'Bruno Fixture', 'bruno@example.test', 'Argentina', 'Basic', 90, false, 1, 1)""")
    for (tid, tdate, pdate, cust, prod, ttype, amount, ccy, usd, merchant, status, in_window, days) in BANK_TRANSACTIONS:
        con.execute("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id,
            product_type, product_status, transaction_type, amount, currency, amount_usd, merchant_name,
            transaction_status, is_within_60_days, days_since_transaction)
            VALUES (?, ?, ?, ?, ?, 'Tarjeta Crédito', 'Active', ?, ?, ?, ?, ?, ?, ?, ?)""",
            [tid, tdate, pdate, cust, prod, ttype, amount, ccy, usd, merchant, status, in_window, days])
        con.execute("""INSERT INTO silver_transactions (transaction_id, transaction_date, process_date, product_id, customer_id,
            transaction_type, amount, currency, merchant_name, transaction_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", [tid, tdate, pdate, prod, cust, ttype, amount, ccy, merchant, status])
    con.close()
    return str(db_path)


@pytest.fixture
def ops_store():
    return OpsStore(":memory:")


@pytest.fixture
def orchestrator(bank_fixture_db, ops_store):
    return DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store)


def make_session(customer_id: str, segment: str = "Plus", country: str = "Colombia", app_role: str = "customer") -> VerifiedSession:
    return VerifiedSession(customer_id=customer_id, name="Fixture Customer", country=country, segment=segment,
                           session_id=f"SESS-{customer_id}", exp=9999999999, app_role=app_role)


@pytest.fixture
def owner_session():
    return make_session("CLI-FIX-OWNER")


@pytest.fixture
def other_session():
    return make_session("CLI-FIX-OTHER", segment="Basic", country="Argentina")
