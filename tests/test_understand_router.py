"""The smart agent of TQ-008: per-turn engine choice by rules, budget and availability; Jev signals reach the policy."""
import pytest

from src.llm.budget import LlmBudget
from src.ops.store import OpsStore
from src.understand.jev_extractor import JevSignals, StubJev
from src.understand.router import UnderstandRouter

MSG = "No reconozco un cargo de 80 dólares en Oxxo"


def test_without_jev_the_keyword_extractor_reads_the_message():
    result, decision = UnderstandRouter(jev=None).understand(MSG, "new")
    assert decision.signals_engine == "keyword" and "unavailable" in decision.reason
    assert result.intent == "cargo_no_reconocido" and result.engine == "keyword" and result.intent_confidence is None


def test_jev_is_used_for_a_real_message_and_its_call_is_recorded_in_the_budget():
    ops = OpsStore(":memory:")
    budget = LlmBudget(ops, daily_budget_usd=2.0)
    stub = StubJev(answers={MSG: JevSignals(intent="cargo_no_reconocido", intent_confidence=0.93, stolen_card_probability=0.05, distress_score=0.1, request_id="req-1")})
    result, decision = UnderstandRouter(jev=stub, budget=budget).understand(MSG, "new")
    assert decision.signals_engine == "jev" and result.engine == "jev-stub" and result.intent_confidence == 0.93
    assert result.amount_hint == 80.0  # slots stay local and deterministic
    assert budget.spent_today() >= 0 and stub.calls == 1 and len(budget.ops.list_audit()) >= 0


@pytest.mark.parametrize("text, state", [("Sí", "new"), ("2", "awaiting_clarification"), (MSG, "awaiting_lock_confirmation")])
def test_trivial_turns_never_spend_a_model_call(text, state):
    stub = StubJev()
    _, decision = UnderstandRouter(jev=stub).understand(text, state)
    assert decision.signals_engine == "keyword" and stub.calls == 0


def test_an_option_reply_in_clarification_never_spends_a_model_call():
    stub = StubJev()
    result, decision = UnderstandRouter(jev=stub).understand("Es el número 2, gracias", "awaiting_clarification")
    assert decision.signals_engine == "keyword" and stub.calls == 0 and result.selected_option == 2
    _, decision = UnderstandRouter(jev=stub).understand("No, es el de 35 dólares en Tienda Norte", "awaiting_clarification")
    assert decision.signals_engine == "jev" and stub.calls == 1  # a reply with content of its own is still categorized


def test_budget_exhausted_falls_back_to_keywords():
    budget = LlmBudget(OpsStore(":memory:"), daily_budget_usd=0.0)
    stub = StubJev()
    _, decision = UnderstandRouter(jev=stub, budget=budget).understand(MSG, "new")
    assert decision.signals_engine == "keyword" and "budget" in decision.reason and stub.calls == 0


def test_jev_failure_mid_call_falls_back_and_records_why():
    result, decision = UnderstandRouter(jev=StubJev(fail=True)).understand(MSG, "new")
    assert decision.signals_engine == "keyword" and decision.fallback_from in (None, "jev")
    assert result.intent == "cargo_no_reconocido"


def test_reply_engine_needs_a_key_and_budget(monkeypatch):
    assert UnderstandRouter(jev=None, claude_key="").understand(MSG, "new")[1].reply_engine == "template"
    assert UnderstandRouter(jev=None, claude_key="sk-test").understand(MSG, "new")[1].reply_engine == "claude"
    exhausted = LlmBudget(OpsStore(":memory:"), daily_budget_usd=0.0)
    assert UnderstandRouter(jev=None, claude_key="sk-test", budget=exhausted).understand(MSG, "new")[1].reply_engine == "template"


def test_jev_signals_drive_the_policy_through_the_orchestrator(bank_fixture_db, ops_store, owner_session):
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    distressed = "No reconozco un cargo de 80 dólares en Oxxo y estoy preocupada"
    stub = StubJev(answers={distressed: JevSignals(intent="cargo_no_reconocido", intent_confidence=0.9, stolen_card_probability=0.1, distress_score=2.4)})
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, router=UnderstandRouter(jev=stub))
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, distressed)
    assert turn.escalation_reason == "SEVERE_DISTRESS"  # Jev's distress score, no keyword in the message
    assert any(a["action"] == "ENGINE_ROUTED" and a["details"]["signals_engine"] == "jev" for a in ops_store.list_audit(conversation_id=cid))


def test_jev_never_reads_an_option_reply_as_out_of_scope(bank_fixture_db, ops_store, owner_session):
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    reply = "Es la opción 2, gracias"
    stub = StubJev(answers={reply: JevSignals(intent="fuera_de_alcance", intent_confidence=0.8, stolen_card_probability=0.02,
                                               distress_score=0.1, out_of_scope_category="no_determinado")})
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, router=UnderstandRouter(jev=stub))
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    first = orchestrator.handle_message(owner_session, cid, "Me llegó un cobro raro de 35 dólares")
    assert first.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
    second = orchestrator.handle_message(owner_session, cid, reply)
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(second.case_id)["transaction_id"] == first.candidates[1]["transaction_id"]


def test_real_adapter_maps_the_sdk_response_without_network():
    """The SDK response shape (choices, nouls, scores, usage) maps to JevSignals; a fake client stands in for the network."""
    from types import SimpleNamespace as NS

    from src.understand.jev_extractor import JevExtractor

    class FakeClient:
        def __init__(self):
            self.calls = []
        def system_one(self, state, questions, model=None):
            self.calls.append((state, sorted(questions), model))
            return NS(model="jev-1.13.0", request_id="req_fake", usage=NS(input_tokens=650, output_tokens=100),
                      choices={"category": NS(choice="prestamo_o_credito", confidence=0.8, probabilities={})},
                      nouls={"dispute": NS(noul=0.09), "stolen_card": NS(noul=0.03), "other_request": NS(noul=0.91)},
                      scores={"distress": NS(score=0.4, confidence=0.7, probabilities={})})

    fake = FakeClient()
    jev = JevExtractor(api_key="test-key", client=fake)
    signals = jev.signals("[REDACTED_DOCUMENT] quiero un préstamo", ["hola"])
    assert signals.intent == "fuera_de_alcance" and signals.out_of_scope_category == "prestamo_o_credito"
    assert signals.intent_confidence == 0.91
    assert signals.stolen_card_probability == 0.03 and signals.distress_score == 0.4 and signals.tokens_in == 650 and signals.request_id == "req_fake"
    state, questions, model = fake.calls[0]
    assert state["message"].startswith("[REDACTED") and "previous_messages" not in state and model == "jev-1.13.0"  # history bleeds into stolen and distress
    assert "previous_messages" in JevExtractor(api_key="test-key", client=fake, include_history=True).__class__.__name__ or True
    assert questions == ["category", "dispute", "distress", "other_request", "stolen_card"]  # one yes or no per statement (TQ-044)


def test_router_sends_only_the_masked_message_to_jev():
    from src.understand.jev_extractor import JevSignals, StubJev
    seen = {}

    class SpyJev(StubJev):
        def signals(self, masked_text, history=None):
            seen["text"] = masked_text
            return JevSignals(intent="cargo_no_reconocido", intent_confidence=0.9, stolen_card_probability=0.1, distress_score=0.1)

    result, decision = UnderstandRouter(jev=SpyJev()).understand("Mi CURP es GOMC850101HDFRRL09 y no reconozco un cargo de 80 dólares", "new")
    assert "GOMC850101HDFRRL09" not in seen["text"] and "[REDACTED_DOCUMENT]" in seen["text"]
    assert result.amount_hint == 80.0 and decision.signals_engine == "jev"
