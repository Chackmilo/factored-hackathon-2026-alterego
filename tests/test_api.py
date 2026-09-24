from fastapi.testclient import TestClient
from src.api.app import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "OmniGuard" in data["app"]

def test_sanitize_endpoint():
    payload = {"text": "Call me at +1 555-123-4567 or email test@gmail.com"}
    response = client.post("/api/v1/sanitize", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "[REDACTED_PHONE]" in data["sanitized_text"]
    assert "[REDACTED_EMAIL]" in data["sanitized_text"]
    assert data["redaction_count"] == 2

def test_triage_emergency_lock():
    payload = {
        "interaction_id": "API-001",
        "customer_id": "C-99",
        "channel": "chat",
        "message_text": "Please lock my card immediately, someone took it."
    }
    response = client.post("/api/v1/triage", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["routing"] == "DETERMINISTIC_FASTPATH"
    assert "LOCK_CARD" in data["actions_taken"]
    assert data["action_status"] == "EXECUTED"

def test_hitl_queue_and_resolution():
    # Trigger an escalation
    payload = {
        "interaction_id": "API-002",
        "customer_id": "C-99",
        "channel": "chat",
        "message_text": "What is this charge?",
        "transaction": {
            "transaction_id": "TX-FRAUD-TEST",
            "amount": 9000.0,
            "currency": "USD",
            "merchant_name": "Luxury Watches",
            "merchant_category": "luxury",
            "location_country": "RU",
            "historical_avg_amount": 50.0
        }
    }
    triage_res = client.post("/api/v1/triage", json=payload)
    assert triage_res.status_code == 200
    assert triage_res.json()["routing"] == "HITL_ESCALATION"

    # Check pending queue
    queue_res = client.get("/api/v1/hitl/queue")
    assert queue_res.status_code == 200
    tickets = queue_res.json()
    assert len(tickets) > 0
    ticket_id = tickets[0]["ticket_id"]

    # Resolve ticket
    resolve_res = client.post("/api/v1/hitl/resolve", json={
        "ticket_id": ticket_id,
        "human_notes": "Reviewed with customer via secure callback. Confirmed fraudulent; charge reversed."
    })
    assert resolve_res.status_code == 200
    assert resolve_res.json()["ticket"]["resolved"] is True
