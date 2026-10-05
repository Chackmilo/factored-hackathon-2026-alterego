"""Topics of a customer message (TQ-044): each statement is read on its own, counted, ordered by criticality and handled one by one."""
from types import SimpleNamespace as NS

import pytest

from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.tools.gateway import BankingToolGateway
from src.understand.jev_extractor import JevExtractor, JevSignals, StubJev, build_questions, merge
from src.understand.keyword_extractor import KeywordIntentExtractor
from src.understand.router import UnderstandRouter
from src.understand.topics import OUT_OF_SCOPE_TOPICS, TOPICS, by_criticality

CARD, CHARGE, BILLING, RULES = "tarjeta_perdida_o_robada", "cargo_no_reconocido", "cobro_indebido", "pregunta_sobre_reglas"


def test_every_topic_is_defined_with_what_it_includes_and_what_it_leaves_out():
    assert set(TOPICS) == {CARD, CHARGE, BILLING, RULES, "prestamo_o_credito", "saldo_o_extracto", "inversion_o_seguro", "soporte_de_tarjeta",
                           "otro_producto"}
    for topic in TOPICS.values():
        assert len(topic.definition) > 60 and len(topic.includes) >= 2 and len(topic.excludes) >= 1, topic.topic_id
        assert topic.title_es and topic.title_pt
    assert set(OUT_OF_SCOPE_TOPICS) == {t.topic_id for t in TOPICS.values() if not t.in_scope}


def test_topics_are_ordered_by_criticality_card_safety_first_and_unrelated_requests_last():
    assert by_criticality(["saldo_o_extracto", RULES, CHARGE, CARD]) == [CARD, CHARGE, RULES, "saldo_o_extracto"]
    assert by_criticality([CHARGE, CHARGE, "saldo_o_extracto"]) == [CHARGE, "saldo_o_extracto"]  # a topic counts once
    assert TOPICS[CARD].criticality < TOPICS[CHARGE].criticality == TOPICS[BILLING].criticality < TOPICS[RULES].criticality


@pytest.mark.parametrize("text, topics, intent", [
    ("No reconozco un cargo de 80 dólares en Oxxo", [CHARGE], "cargo_no_reconocido"),
    ("Me cobraron dos veces la compra de 80 dólares", [BILLING], "cobro_indebido"),
    ("Perdí la tarjeta ayer y me aparece un cobro de 80 dólares que yo no hice", [CARD, CHARGE], "cargo_no_reconocido"),
    ("Perdí la tarjeta", [CARD], "tarjeta_robada"),
    ("No reconozco un cargo de 80 dólares. Dame mi saldo por favor.", [CHARGE, "saldo_o_extracto"], "cargo_no_reconocido"),
    ("No reconozco un cargo de 80 dólares y necesito un préstamo", [CHARGE, "prestamo_o_credito"], "cargo_no_reconocido"),
    ("Não reconheço uma cobrança de 80 dólares e quero um empréstimo", [CHARGE, "prestamo_o_credito"], "cargo_no_reconocido"),
    ("Roubaram meu cartão e agora vejo uma compra de 300 dólares que não fiz. Qual é o meu saldo?", [CARD, CHARGE, "saldo_o_extracto"],
     "cargo_no_reconocido"),
    # the statement is where the charge shows up, and a loan installment is not a card charge: both stay as they were
    ("Revisando mi extracto vi un movimiento de 80 dólares que no es mío", [CHARGE], "cargo_no_reconocido"),
    ("Revisé mi extracto y vi un cargo de 80 dólares que no reconozco", [CHARGE], "cargo_no_reconocido"),
    ("No reconozco el cobro de la cuota del préstamo", ["prestamo_o_credito"], "fuera_de_alcance"),
    ("¿Cuál es mi saldo?", ["saldo_o_extracto"], "fuera_de_alcance"),
    ("¿Cuántos días tengo para disputar un cargo?", [RULES], "cargo_no_reconocido"),
    ("Hola", [], "consulta_general"),
])
def test_the_keyword_extractor_names_every_topic_of_a_message(text, topics, intent):
    result = KeywordIntentExtractor().extract(text)
    assert result.topics == topics and result.intent == intent
    assert result.as_signals()["topics"] == topics and result.as_signals()["topic_count"] == len(topics)


# ------------------------------------------------------------ Jev: one independent question per statement
def _fake_client(dispute, stolen, other, category="no_determinado"):
    class FakeClient:
        def system_one(self, state, questions, model=None):
            self.questions = sorted(questions)
            return NS(model="jev-1.13.0", request_id="req_fake", usage=NS(input_tokens=700, output_tokens=90),
                      choices={"category": NS(choice=category, confidence=0.9, probabilities={})},
                      nouls={"dispute": NS(noul=dispute), "stolen_card": NS(noul=stolen), "other_request": NS(noul=other)},
                      scores={"distress": NS(score=0.4, confidence=0.7, probabilities={})})
    return FakeClient()


def test_jev_is_asked_one_yes_or_no_question_per_statement_and_never_to_pick_one_intent():
    questions = build_questions()
    assert sorted(questions) == ["category", "dispute", "distress", "other_request", "stolen_card"]
    assert type(questions["dispute"]).__name__ == type(questions["stolen_card"]).__name__ == type(questions["other_request"]).__name__ == "Noul"


def test_a_stolen_card_and_an_unrecognized_charge_in_one_message_are_two_confident_statements():
    """The case that lost confidence when Jev had to pick one intent (0.64 for tarjeta_robada): each statement keeps its own."""
    text = "Roubaram meu cartão e agora vejo uma compra de 300 dólares que não fiz."
    signals = JevExtractor(api_key="k", client=_fake_client(dispute=0.97, stolen=0.93, other=0.02)).signals(text)
    assert signals.intent == "cargo_no_reconocido" and signals.intent_confidence == 0.97 and signals.stolen_card_probability == 0.93
    result = merge(KeywordIntentExtractor().extract(text), signals, "jev")
    assert result.topics == [CARD, CHARGE] and result.intent == "cargo_no_reconocido" and result.intent_confidence == 0.97


def test_jev_reads_an_unrelated_request_beside_a_dispute_as_a_second_topic():
    text = "No reconozco un cargo de 80 dólares. Y quiero saber cómo pedir un préstamo."
    signals = JevExtractor(api_key="k", client=_fake_client(dispute=0.95, stolen=0.02, other=0.9, category="prestamo_o_credito")).signals(text)
    result = merge(KeywordIntentExtractor().extract(text), signals, "jev")
    assert result.intent == "cargo_no_reconocido" and result.out_of_scope_category is None  # the dispute is handled
    assert result.topics == [CHARGE, "prestamo_o_credito"]


def test_jev_reads_a_message_without_a_dispute_as_out_of_scope_or_general():
    loan = JevExtractor(api_key="k", client=_fake_client(dispute=0.03, stolen=0.01, other=0.92, category="prestamo_o_credito")).signals("Quiero un préstamo")
    assert (loan.intent, loan.intent_confidence, loan.out_of_scope_category) == ("fuera_de_alcance", 0.92, "prestamo_o_credito")
    hello = JevExtractor(api_key="k", client=_fake_client(dispute=0.04, stolen=0.01, other=0.05)).signals("Hola, buenas tardes")
    assert hello.intent == "consulta_general" and hello.intent_confidence == pytest.approx(0.95)
    unsure = JevExtractor(api_key="k", client=_fake_client(dispute=0.55, stolen=0.01, other=0.05)).signals("Vi algo raro")
    assert unsure.intent == "cargo_no_reconocido" and unsure.intent_confidence == 0.55  # under 0.70: POL-CLARIFY asks


def test_a_stub_or_legacy_answer_without_the_new_probabilities_still_gets_its_topics():
    text = "Perdí la tarjeta ayer y me aparece un cobro de 80 dólares que yo no hice"
    result = merge(KeywordIntentExtractor().extract(text), JevSignals(intent="cargo_no_reconocido", intent_confidence=0.9,
                                                                    stolen_card_probability=0.9, distress_score=0.1), "jev-stub")
    assert result.topics == [CARD, CHARGE]


# ------------------------------------------------------------ the conversation: one by one, by criticality
def _topics_audit(ops_store, cid):
    return [a["details"] for a in ops_store.list_audit(conversation_id=cid) if a["action"] == "TOPICS_DETECTED"]


def test_several_topics_are_announced_counted_out_of_sight_and_taken_one_by_one(orchestrator, owner_session, ops_store):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta y no reconozco un cargo de 120 dólares en Cine Premium")
    assert turn.reply.startswith("Veo que nos escribe por más de un tema. Los atenderemos uno por uno, empezando por el más urgente.")
    assert turn.state == "awaiting_lock_confirmation"  # the card comes first
    assert _topics_audit(ops_store, cid) == [{"topic_count": 2, "topics": [CARD, CHARGE]}]
    assert turn.signals["topic_count"] == 2 and "2 temas" not in turn.reply and "dos temas" not in turn.reply


def test_an_unrelated_request_beside_a_dispute_is_named_as_not_handled_here_and_the_dispute_goes_on(orchestrator, owner_session, ops_store):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 120 dólares en Cine Premium. Dame mi saldo por favor.")
    assert turn.case_id and turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert turn.reply.startswith("Veo que nos escribe por más de un tema.")
    assert "saldos y extractos" in turn.reply and "no corresponde a este canal" in turn.reply
    assert _topics_audit(ops_store, cid) == [{"topic_count": 2, "topics": [CHARGE, "saldo_o_extracto"]}]


def test_the_same_in_portuguese(orchestrator, owner_session):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "Não reconheço uma cobrança de 120 dólares no Cine Premium. Qual é o meu saldo?")
    assert turn.language == "pt" and turn.case_id
    assert turn.reply.startswith("Vejo que você nos escreve por mais de um assunto.") and "saldos e extratos" in turn.reply


def test_one_topic_gets_no_announcement_and_an_unrelated_request_alone_keeps_its_abstention(orchestrator, owner_session, ops_store):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    one = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 120 dólares en Cine Premium")
    assert not one.reply.startswith("Veo que") and _topics_audit(ops_store, cid) == [] and one.signals["topic_count"] == 1
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    alone = orchestrator.handle_message(owner_session, cid, "¿Cuál es mi saldo?")
    assert alone.escalation_reason == "OUT_OF_SCOPE_INTENT" and alone.reply.count("saldos y extractos") == 1
    assert not alone.reply.startswith("Veo que")


def test_with_jev_the_two_statements_reach_the_policy_and_a_charge_over_500_reaches_a_human(bank_fixture_db, ops_store, owner_session):
    """The held-out failure of 5-Oct: stolen card plus a large charge got a clarification because one intent had to win."""
    text = "Me robaron la tarjeta y ahora veo un cargo de 850 dólares en Super Ahorro que no hice"
    stub = StubJev(answers={text: JevSignals(intent="cargo_no_reconocido", intent_confidence=0.97, stolen_card_probability=0.93, distress_score=0.3,
                                             dispute_probability=0.97, other_request_probability=0.02)})
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, router=UnderstandRouter(jev=stub, claude_key=""))
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, text)
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "AMOUNT_EXCEEDS_500_USD" and turn.handoff_id
    assert turn.lock_offer is not None and turn.signals["topics"] == [CARD, CHARGE]
