"""
Unit tests for the Factored Hackathon Dispute Intake Flow:
- Dispute Policy Engine (window check, caps, escalation, clause citations)
- Zero-Trust Session & Authorization (JWT token, customer isolation)
- Tool Gateway with Act-and-Verify
"""
import duckdb
import pytest
from datetime import datetime, date, timedelta
from fastapi import HTTPException

from src.rules.dispute_policy import DisputePolicyEngine, DisputePolicyInput
from src.auth.session import create_test_session, decode_session_token, VerifiedSession
from src.tools.gateway import BankingToolGateway, UnauthorizedAccessError, ActionVerificationError, RecordNotFoundError

def test_dispute_policy_out_of_window_abstention():
    """Policy must safely abstain if transaction is older than 60 days (POL-WIN-60)."""
    p_input = DisputePolicyInput(
        customer_id="CLI-TEST01",
        customer_segment="Plus",
        customer_country="Colombia",
        account_age_days=300,
        complaints_last_90d=0,
        transaction_id="TRX-OLD",
        transaction_date=date(2026, 3, 1),  # > 60 days from anchor 2026-06-17 (~108 days)
        transaction_amount=100.0,
        transaction_currency="USD",
        amount_usd=100.0,
        current_date=date(2026, 6, 17)
    )
    decision = DisputePolicyEngine.evaluate(p_input)
    assert not decision.is_eligible
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert "POL-WIN-60" in decision.cited_clauses
    assert decision.action_required == "ABSTAIN"
    assert "60 días" in decision.explanation_es

@pytest.mark.parametrize("transaction_date, expected_outcome", [
    # 03:00 UTC belongs to the bank process day 2026-04-17: 61 days before 2026-06-17
    (datetime(2026, 4, 18, 3, 0), "SAFE_POLICY_ABSTENTION"),
    # 06:00 UTC opens the process day 2026-04-18: 60 days, still in window
    (datetime(2026, 4, 18, 6, 0), "AUTONOMOUS_RESOLUTION"),
])
def test_dispute_policy_window_counts_bank_process_day(transaction_date, expected_outcome):
    """POL-WIN-60 counts days from process_date = date(transaction_date - 6 h), not the UTC calendar date."""
    p_input = DisputePolicyInput(
        customer_id="CLI-TEST04",
        customer_segment="Plus",
        customer_country="Colombia",
        account_age_days=300,
        complaints_last_90d=0,
        transaction_id="TRX-EDGE",
        transaction_date=transaction_date,
        transaction_amount=100.0,
        transaction_currency="USD",
        amount_usd=100.0,
        current_date=date(2026, 6, 17)
    )
    assert DisputePolicyEngine.evaluate(p_input).policy_outcome == expected_outcome

def test_dispute_policy_autonomous_provisional_credit():
    """Eligible <= $150 USD for Plus customer must receive simulated provisional credit (POL-AUT-150)."""
    p_input = DisputePolicyInput(
        customer_id="CLI-TEST01",
        customer_segment="Plus",
        customer_country="Colombia",
        account_age_days=250,
        complaints_last_90d=0,
        transaction_id="TRX-RECENT",
        transaction_date=date(2026, 6, 10),  # 7 days ago
        transaction_amount=120.0,
        transaction_currency="USD",
        amount_usd=120.0,
        current_date=date(2026, 6, 17)
    )
    decision = DisputePolicyEngine.evaluate(p_input)
    assert decision.is_eligible
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.provisional_credit_eligible
    assert decision.provisional_credit_amount_usd == 120.0
    assert "POL-AUT-150" in decision.cited_clauses
    assert decision.action_required == "OPEN_DISPUTE_AND_CREDIT"

def test_dispute_policy_high_value_escalation():
    """Amounts > $500 USD must trigger mandatory HITL escalation (POL-ESC-500)."""
    p_input = DisputePolicyInput(
        customer_id="CLI-TEST02",
        customer_segment="Premium",
        customer_country="México",
        account_age_days=400,
        complaints_last_90d=0,
        transaction_id="TRX-EXPENSIVE",
        transaction_date=date(2026, 6, 12),
        transaction_amount=850.0,
        transaction_currency="USD",
        amount_usd=850.0,
        current_date=date(2026, 6, 17)
    )
    decision = DisputePolicyEngine.evaluate(p_input)
    assert decision.is_eligible
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert not decision.provisional_credit_eligible
    assert "POL-ESC-500" in decision.cited_clauses
    assert decision.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    assert decision.action_required == "HOLD_CARD_AND_ESCALATE"

def test_dispute_policy_regulator_or_legal_citing():
    """Citing financial regulator or legal action triggers mandatory escalation (POL-ESC-LEGAL)."""
    p_input = DisputePolicyInput(
        customer_id="CLI-TEST03",
        customer_segment="Basic",
        customer_country="México",
        account_age_days=200,
        complaints_last_90d=0,
        transaction_id="TRX-REG",
        transaction_date=date(2026, 6, 14),
        transaction_amount=50.0,
        transaction_currency="USD",
        amount_usd=50.0,
        customer_message="Si no me solucionan voy a poner la queja en CONDUSEF inmediatamente",
        current_date=date(2026, 6, 17)
    )
    decision = DisputePolicyEngine.evaluate(p_input)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert "POL-ESC-LEGAL" in decision.cited_clauses
    assert decision.escalation_reason == "REGULATOR_OR_LEGAL_CITING"

def test_session_token_verification_and_expiry():
    """Zero-trust JWT verification test."""
    token = create_test_session(
        customer_id="CLI-TEST99",
        name="Elena Rostova",
        country="Colombia",
        segment="Premium",
        ttl_seconds=3600
    )
    session = decode_session_token(token)
    assert session.customer_id == "CLI-TEST99"
    assert session.name == "Elena Rostova"
    assert session.segment == "Premium"

    # Expired token test
    expired_token = create_test_session(
        customer_id="CLI-EXPIRED",
        ttl_seconds=-10
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_session_token(expired_token)
    assert exc_info.value.status_code == 401

@pytest.fixture
def fixture_db(tmp_path):
    """
    Team-generated test fixture: a tiny system of record using the lakehouse table schemas.
    CLI-FIX-OWNER owns card PRD-FIX-OWNER and transaction TRX-FIX-001.
    CLI-FIX-OTHER owns card PRD-FIX-OTHER. CLI-FIX-GHOST exists nowhere.
    """
    db_path = tmp_path / "fixture_lakehouse.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE silver_products (
            product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, product_number VARCHAR,
            currency VARCHAR, current_balance DOUBLE, credit_limit DOUBLE, interest_rate DOUBLE,
            opening_date DATE, expiration_date DATE, opening_branch_id VARCHAR, product_status VARCHAR,
            opening_channel VARCHAR, has_linked_app BOOLEAN, days_past_due DOUBLE,
            last_transaction_date TIMESTAMP, last_updated TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE silver_transactions (
            transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, product_id VARCHAR,
            customer_id VARCHAR, transaction_type VARCHAR, transaction_category VARCHAR, amount DOUBLE,
            currency VARCHAR, amount_usd DOUBLE, channel VARCHAR, branch_id VARCHAR, merchant_name VARCHAR,
            merchant_category VARCHAR, transaction_country VARCHAR, transaction_city VARCHAR,
            transaction_status VARCHAR, response_code VARCHAR, is_fraud BOOLEAN, fraud_score DOUBLE,
            latitude DOUBLE, longitude DOUBLE, day VARCHAR, month VARCHAR, year BIGINT
        )
    """)
    con.execute("""
        CREATE TABLE silver_complaints (
            complaint_id VARCHAR, creation_date TIMESTAMP, process_date DATE, customer_id VARCHAR,
            case_type VARCHAR, category VARCHAR, subcategory VARCHAR, reception_channel VARCHAR,
            affected_product_id VARCHAR, related_branch_id VARCHAR, origin_interaction_id VARCHAR,
            description VARCHAR, claimed_amount DOUBLE, currency VARCHAR, priority VARCHAR, status VARCHAR,
            assigned_agent_id VARCHAR, assignment_date TIMESTAMP, first_response_date TIMESTAMP,
            resolution_date TIMESTAMP, closing_date TIMESTAMP, sla_breached BOOLEAN, resolution_days DOUBLE,
            resolution VARCHAR, compensation_granted DOUBLE, resolution_satisfaction DOUBLE,
            is_repeat_complainer BOOLEAN, day VARCHAR, month VARCHAR, year BIGINT
        )
    """)
    con.execute("""
        CREATE TABLE gold_customers (
            customer_id VARCHAR, document_number VARCHAR, document_type VARCHAR, first_name VARCHAR,
            last_name VARCHAR, full_name VARCHAR, email VARCHAR, mobile_phone VARCHAR, country VARCHAR,
            city VARCHAR, segment VARCHAR, credit_score DOUBLE, registration_date TIMESTAMP,
            customer_status VARCHAR, accepts_marketing BOOLEAN, account_age_days BIGINT,
            is_account_mature BOOLEAN, complaints_last_90d BIGINT, active_products BIGINT
        )
    """)
    con.execute("""
        CREATE TABLE gold_transactions (
            transaction_id VARCHAR, transaction_date TIMESTAMP, process_date DATE, customer_id VARCHAR,
            product_id VARCHAR, product_type VARCHAR, product_status VARCHAR, transaction_type VARCHAR,
            amount DOUBLE, currency VARCHAR, amount_usd DOUBLE, amount_usd_normalized DOUBLE, channel VARCHAR,
            merchant_name VARCHAR, merchant_category VARCHAR, transaction_country VARCHAR,
            transaction_city VARCHAR, transaction_status VARCHAR, is_fraud BOOLEAN, fraud_score DOUBLE,
            is_within_60_days BOOLEAN, days_since_transaction BIGINT
        )
    """)
    # 03:15 UTC on 2026-06-10 belongs to the bank process day 2026-06-09
    con.execute("""
        INSERT INTO gold_transactions
            (transaction_id, transaction_date, process_date, customer_id, product_id, amount, currency,
             amount_usd_normalized, merchant_name, transaction_status, is_within_60_days, days_since_transaction)
        VALUES ('TRX-FIX-002', TIMESTAMP '2026-06-10 03:15:00', DATE '2026-06-09', 'CLI-FIX-OWNER',
                'PRD-FIX-OWNER', 80.0, 'USD', 80.0, 'Oxxo', 'Approved', true, 8)
    """)
    con.execute("""
        INSERT INTO silver_products (product_id, customer_id, product_type, product_status) VALUES
            ('PRD-FIX-OWNER', 'CLI-FIX-OWNER', 'Tarjeta de Credito', 'Active'),
            ('PRD-FIX-OTHER', 'CLI-FIX-OTHER', 'Tarjeta de Debito', 'Active')
    """)
    con.execute("""
        INSERT INTO silver_transactions
            (transaction_id, transaction_date, process_date, product_id, customer_id, amount, currency, merchant_name)
        VALUES ('TRX-FIX-001', TIMESTAMP '2026-06-10 14:22:00', DATE '2026-06-10',
                'PRD-FIX-OWNER', 'CLI-FIX-OWNER', 120.0, 'USD', 'Oxxo')
    """)
    con.execute("""
        INSERT INTO gold_customers
            (customer_id, full_name, email, country, segment, account_age_days,
             is_account_mature, complaints_last_90d, active_products)
        VALUES ('CLI-FIX-OWNER', 'Ana Fixture', 'ana@example.test', 'Colombia', 'Plus', 250, true, 2, 1)
    """)
    con.close()
    return str(db_path)

def _session(customer_id: str) -> VerifiedSession:
    return VerifiedSession(
        customer_id=customer_id,
        name="Fixture Customer",
        country="Colombia",
        segment="Plus",
        session_id="SESS-FIX",
        exp=9999999999
    )

def _fetch(db_path: str, query: str, params: list):
    con = duckdb.connect(db_path)
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()

def test_customer_profile_unknown_customer_raises(fixture_db):
    """A customer missing from the system of record must not receive invented facts that unlock POL-AUT-150."""
    gateway = BankingToolGateway(db_path=fixture_db)
    with pytest.raises(RecordNotFoundError):
        gateway.get_customer_profile(_session("CLI-FIX-GHOST"))

def test_customer_profile_returns_stored_facts(fixture_db):
    gateway = BankingToolGateway(db_path=fixture_db)
    profile = gateway.get_customer_profile(_session("CLI-FIX-OWNER"))
    assert profile["account_age_days"] == 250
    assert profile["complaints_last_90d"] == 2

def test_customer_profile_exposes_no_contact_or_document_data(fixture_db):
    """Minimization (rule 10): the profile carries only policy facts; bank.customers will not hold contacts or documents."""
    gateway = BankingToolGateway(db_path=fixture_db)
    profile = gateway.get_customer_profile(_session("CLI-FIX-OWNER"))
    assert not {"email", "mobile_phone", "document_number"} & profile.keys()

def test_search_returns_bank_process_day(fixture_db):
    """The window counts from process_date, so the search must hand it over next to the UTC transaction_date."""
    gateway = BankingToolGateway(db_path=fixture_db)
    [row] = gateway.search_customer_transactions(_session("CLI-FIX-OWNER"))
    assert row["transaction_date"] == "2026-06-10T03:15:00"
    assert row["process_date"] == "2026-06-09"

def test_lock_card_blocks_owned_card(fixture_db):
    gateway = BankingToolGateway(db_path=fixture_db)
    result = gateway.execute_lock_card(_session("CLI-FIX-OWNER"), "PRD-FIX-OWNER")
    assert result["verified"] is True
    assert _fetch(fixture_db, "SELECT product_status FROM silver_products WHERE product_id = ?", ["PRD-FIX-OWNER"]) == [("Blocked",)]

def test_lock_card_rejects_other_customers_card(fixture_db):
    gateway = BankingToolGateway(db_path=fixture_db)
    with pytest.raises(UnauthorizedAccessError):
        gateway.execute_lock_card(_session("CLI-FIX-OWNER"), "PRD-FIX-OTHER")
    assert _fetch(fixture_db, "SELECT product_status FROM silver_products WHERE product_id = ?", ["PRD-FIX-OTHER"]) == [("Active",)]

def test_open_dispute_persists_case(fixture_db):
    gateway = BankingToolGateway(db_path=fixture_db)
    result = gateway.execute_open_dispute(
        _session("CLI-FIX-OWNER"), "TRX-FIX-001",
        dispute_reason="No reconozco el cargo", claimed_amount=120.0, currency="USD"
    )
    stored = _fetch(
        fixture_db,
        "SELECT customer_id, affected_product_id, claimed_amount, status FROM silver_complaints WHERE complaint_id = ?",
        [result["case_id"]]
    )
    assert stored == [("CLI-FIX-OWNER", "PRD-FIX-OWNER", 120.0, "INTAKE_RECEIVED")]

def test_open_dispute_rejects_other_customers_transaction(fixture_db):
    gateway = BankingToolGateway(db_path=fixture_db)
    with pytest.raises(UnauthorizedAccessError):
        gateway.execute_open_dispute(
            _session("CLI-FIX-OTHER"), "TRX-FIX-001",
            dispute_reason="Intento cruzado", claimed_amount=120.0, currency="USD"
        )
    assert _fetch(fixture_db, "SELECT COUNT(*) FROM silver_complaints", []) == [(0,)]
