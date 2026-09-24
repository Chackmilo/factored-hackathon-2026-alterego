import pytest
from src.agents.orchestrator import HybridOrchestrator
from src.domain.schemas import CustomerInteractionInput, TransactionContext
from src.domain.enums import TriageRouting, ActionStatus

@pytest.fixture
def orchestrator():
    return HybridOrchestrator()

def test_triage_deterministic_card_lock(orchestrator):
    inp = CustomerInteractionInput(
        interaction_id="IT-01",
        customer_id="C-100",
        message_text="Emergency: Please lock my card right now."
    )
    decision = orchestrator.process_interaction(inp)
    assert decision.routing == TriageRouting.DETERMINISTIC_FASTPATH
    assert decision.action_status == ActionStatus.EXECUTED
    assert "LOCK_CARD" in decision.actions_taken
    assert decision.execution_metrics["total_latency_ms"] < 200.0

def test_triage_high_fraud_escalates_to_hitl(orchestrator):
    inp = CustomerInteractionInput(
        interaction_id="IT-02",
        customer_id="C-200",
        message_text="What is this charge?",
        transaction=TransactionContext(
            transaction_id="TX-HIGH",
            amount=4500.0,
            merchant_name="Foreign Tech Wholesaler",
            merchant_category="electronics",
            location_country="RU",
            is_card_present=False,
            historical_avg_amount=40.0
        )
    )
    decision = orchestrator.process_interaction(inp)
    assert decision.routing == TriageRouting.HITL_ESCALATION
    assert decision.action_status == ActionStatus.PENDING_HUMAN_APPROVAL
    assert decision.hitl_ticket is not None
    assert decision.ml_result.fraud_probability > 0.80

def test_triage_autonomous_dispute_tool(orchestrator):
    inp = CustomerInteractionInput(
        interaction_id="IT-03",
        customer_id="C-300",
        message_text="I dispute this streaming charge of $20.00.",
        transaction=TransactionContext(
            transaction_id="TX-LOW",
            amount=20.0,
            merchant_name="Streaming Network",
            merchant_category="entertainment",
            location_country="US",
            historical_avg_amount=30.0
        )
    )
    decision = orchestrator.process_interaction(inp)
    assert decision.routing == TriageRouting.AGENTIC_WORKFLOW
    assert decision.action_status == ActionStatus.EXECUTED
    assert len(decision.agent_steps) > 0
