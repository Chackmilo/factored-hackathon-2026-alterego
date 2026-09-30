"""HTTP contract of the dispute endpoints and the console role check, over the fixture bank and an in-memory ops store."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.api.dispute_routes import get_orchestrator
from src.auth.session import create_test_session
from src.ops.store import OpsStore
from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.tools.gateway import BankingToolGateway


@pytest.fixture
def api(bank_fixture_db):
    orch = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=OpsStore(":memory:"))
    app.dependency_overrides[get_orchestrator] = lambda: orch
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)


def bearer(customer_id="CLI-FIX-OWNER", app_role="customer"):
    return {"Authorization": f"Bearer {create_test_session(customer_id=customer_id, app_role=app_role)}"}


def test_local_issuer_reads_facts_from_the_system_of_record(api):
    personas = api.get("/api/v1/auth/personas").json()
    assert {p["customer_id"] for p in personas} == {"CLI-FIX-OWNER", "CLI-FIX-OTHER"}
    assert "full_name" not in personas[0] and "email" not in personas[0]
    res = api.post("/api/v1/auth/test-session", json={"customer_id": "CLI-FIX-OWNER"})
    assert res.status_code == 200 and res.json()["segment"] == "Plus"
    assert api.post("/api/v1/auth/test-session", json={"customer_id": "CLI-FIX-GHOST"}).status_code == 404


def test_conversation_requires_a_session(api):
    assert api.post("/api/v1/disputes/conversations", json={"language": "es"}).status_code == 401


def test_customer_flow_over_http(api):
    headers = bearer()
    conv = api.post("/api/v1/disputes/conversations", json={"language": "es"}, headers=headers)
    assert conv.status_code == 201
    cid = conv.json()["conversation_id"]
    turn = api.post(f"/api/v1/disputes/conversations/{cid}/messages", json={"text": "No reconozco un cargo de 80 dólares en Oxxo"}, headers=headers)
    assert turn.status_code == 200
    body = turn.json()
    assert body["policy_outcome"] == "AUTONOMOUS_RESOLUTION" and body["case_id"]
    history = api.get(f"/api/v1/disputes/conversations/{cid}", headers=headers).json()
    assert [m["role"] for m in history["messages"]] == ["customer", "assistant"]
    # another customer gets the same "not found" as a missing id: ids cannot be probed
    assert api.get(f"/api/v1/disputes/conversations/{cid}", headers=bearer("CLI-FIX-OTHER")).status_code == 404
    assert api.get("/api/v1/disputes/conversations/CONV-DOES-NOT-EXIST", headers=bearer("CLI-FIX-OTHER")).status_code == 404


def test_console_requires_the_agent_role(api):
    assert api.get("/api/v1/console/cases", headers=bearer()).status_code == 403
    assert api.get("/api/v1/console/cases", headers=bearer("AGENT-1", app_role="agent")).status_code == 200


def test_agent_reviews_credit_candidate_and_handoff(api):
    customer = bearer()
    agent = bearer("AGENT-1", app_role="agent")
    cid = api.post("/api/v1/disputes/conversations", json={"language": "es"}, headers=customer).json()["conversation_id"]
    case_id = api.post(f"/api/v1/disputes/conversations/{cid}/messages", json={"text": "No reconozco un cargo de 80 dólares en Oxxo"}, headers=customer).json()["case_id"]
    handoff_id = api.post(f"/api/v1/disputes/conversations/{cid}/messages", json={"text": "No reconozco un cargo de 850 dólares en Super Ahorro"}, headers=customer).json()["handoff_id"]

    candidates = api.get("/api/v1/console/cases", params={"credit_candidates": "true"}, headers=agent).json()
    assert [c["case_id"] for c in candidates] == [case_id]
    decided = api.post(f"/api/v1/console/cases/{case_id}/credit-decision", json={"decision": "approved"}, headers=agent).json()
    assert decided["credit_decision"] == "approved" and decided["credit_decided_by"] == "AGENT-1"
    assert api.post(f"/api/v1/console/cases/{case_id}/credit-decision", json={"decision": "approved"}, headers=customer).status_code == 403

    handoffs = api.get("/api/v1/console/handoffs", params={"status_filter": "open"}, headers=agent).json()
    assert [h["handoff_id"] for h in handoffs] == [handoff_id]
    assert handoffs[0]["packet"]["escalation_reason"] == "AMOUNT_EXCEEDS_500_USD"
    resolved = api.post(f"/api/v1/console/handoffs/{handoff_id}/resolve", headers=agent).json()
    assert resolved["status"] == "resolved"
    audit = api.get("/api/v1/console/audit", params={"conversation_id": cid}, headers=agent).json()
    assert {a["action"] for a in audit} >= {"OPEN_DISPUTE", "CREATE_HANDOFF", "CREDIT_CANDIDATE_DECISION", "HANDOFF_RESOLVED"}


def test_team_questions_live_in_the_console(api):
    agent = bearer("AGENT-1", app_role="agent")
    assert api.get("/api/v1/console/questions", headers=bearer()).status_code == 403
    # the API seeds the fixture on startup; the test orchestrator is built directly, so seed here
    api.app.dependency_overrides[get_orchestrator]().ops.seed_questions()
    open_questions = api.get("/api/v1/console/questions", params={"status_filter": "open"}, headers=agent).json()
    assert {q["question_id"] for q in open_questions} >= {"TQ-002", "TQ-016", "TQ-019"}
    assert "TQ-001" not in {q["question_id"] for q in open_questions}  # answered in chat, recorded in the fixture
    answered = api.post("/api/v1/console/questions/TQ-016/answer", json={"answer": "Skip with reason"}, headers=agent).json()
    assert answered["status"] == "answered" and answered["answered_by"] == "AGENT-1"
    filed = api.post("/api/v1/console/questions", json={"topic": "Loop", "question": "Should the loop run the full load?", "options": ["yes", "no"]}, headers=agent)
    assert filed.status_code == 201 and filed.json()["status"] == "open"
    assert api.post("/api/v1/console/questions/TQ-404/answer", json={"answer": "x"}, headers=agent).status_code == 404
