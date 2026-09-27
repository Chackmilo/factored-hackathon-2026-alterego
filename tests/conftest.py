"""
Shared pytest fixtures for OmniGuard AI / Dispute Intake test suite.
"""
from datetime import date
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.auth.session import create_test_session
from src.rules.dispute_policy import DisputePolicyInput

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
        current_date=date(2026, 6, 17),
    )
