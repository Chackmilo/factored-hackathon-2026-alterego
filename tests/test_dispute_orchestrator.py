"""
End-to-end turns of the dispute orchestrator over the team-generated bank fixture and an in-memory ops store.
Covers the three case types (normal, ambiguous or unsupported, human required) in Spanish and Portuguese.
"""
from datetime import datetime, timedelta

import pytest

from src.tools.gateway import ActionVerificationError, UnauthorizedAccessError


def start(orchestrator, session):
    return orchestrator.start_conversation(session)["conversation_id"]


def fetch(db_path, sql, params):
    import duckdb
    con = duckdb.connect(db_path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def raising(exc):
    """A gateway method that fails the way a timed-out or broken system of record does."""
    def fail(*args, **kwargs):
        raise exc
    return fail


def test_normal_dispute_es_opens_verified_case_with_credit_candidate(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert turn.language == "es"
    assert turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert turn.case_id and turn.case_id in turn.reply
    assert "registrada" in turn.reply and "crédito" not in turn.reply.lower()
    assert turn.state == "closed"
    case = ops_store.get_case(turn.case_id)
    assert case["transaction_id"] == "TRX-A-080" and case["status"] == "Open" and case["subcategory"] == "Cargo no reconocido"
    assert case["provisional_credit_candidate"] is True and case["provisional_credit_amount_usd"] == 80.0
    audit = [a for a in ops_store.list_audit(conversation_id=cid) if a["action"] == "OPEN_DISPUTE"]
    assert audit and audit[0]["verified"] is True


def test_normal_dispute_pt_replies_in_portuguese(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Não reconheço uma compra de 120 dólares no Cine Premium")
    assert turn.language == "pt"
    assert turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert "registrada" in turn.reply and "análise" in turn.reply
    assert ops_store.get_case(turn.case_id)["transaction_id"] == "TRX-A-120"


@pytest.mark.parametrize("text, language, transaction_id", [
    ("Revisé el estado de cuenta del mes y aparece un cargo de 80 dólares en Oxxo que no reconozco", "es", "TRX-A-080"),
    ("No meu extrato apareceu uma compra de 120 dólares no Cine Premium que não fiz", "pt", "TRX-A-120"),
])
def test_statement_mention_with_dispute_language_opens_the_case(orchestrator, owner_session, ops_store, text, language, transaction_id):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, text)
    assert turn.language == language and turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(turn.case_id)["transaction_id"] == transaction_id


@pytest.mark.parametrize("text, language, transaction_id", [
    ("Vi en el extracto un cargo de 120 dólares en Cine Premium que no es mío", "es", "TRX-A-120"),
    ("No extrato tem uma compra de 80 dólares no Oxxo que não é minha", "pt", "TRX-A-080"),
])
def test_a_charge_said_not_to_be_mine_opens_the_case(orchestrator, owner_session, ops_store, text, language, transaction_id):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, text)
    assert turn.language == language and turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(turn.case_id)["transaction_id"] == transaction_id


def test_a_high_value_charge_said_not_to_be_mine_goes_to_a_human(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "En el estado de cuenta me sale una compra de 850 dólares en Super Ahorro que no es mía")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    assert turn.handoff_id and ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []


@pytest.mark.parametrize("text, named", [
    ("No reconozco tres cargos de mi tarjeta: 80, 120 y 850 dólares. Creo que la clonaron.", ["TRX-A-080", "TRX-A-120", "TRX-A-850"]),
    ("Não reconheço três compras no meu cartão: 80, 120 e 850 dólares.", ["TRX-A-080", "TRX-A-120", "TRX-A-850"]),
    # the declined 45 counts as a named charge; the turn is decided on the first disputable one
    ("No reconozco cargos de 45, 80 y 120 dólares", ["TRX-A-DECL", "TRX-A-080", "TRX-A-120"]),
])
def test_three_charges_named_at_once_go_to_a_human_with_a_lock_offer(orchestrator, owner_session, ops_store, text, named):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, text)
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "MULTIPLE_CHARGES_48H"
    assert turn.lock_offer["reason"] == "MULTI_CHARGE_FRAUD" and turn.state == "awaiting_lock_confirmation"
    assert ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []
    facts = " ".join(ops_store.get_handoff(turn.handoff_id)["packet"]["verified_facts"])
    assert all(transaction_id in facts for transaction_id in named)


def test_two_charges_named_at_once_are_listed_and_the_other_is_remembered(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "No reconozco dos cargos: 80 y 120 dólares")
    assert first.policy_outcome == "CLARIFICATION_REQUIRED" and first.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
    assert [c["transaction_id"] for c in first.candidates] == ["TRX-A-120", "TRX-A-080"]  # most recent first
    second = orchestrator.handle_message(owner_session, cid, "1")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(second.case_id)["transaction_id"] == "TRX-A-120"
    assert "cargos que mencionó" in second.reply


def test_amounts_that_match_several_charges_list_every_match(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco dos cargos: 35 y 80 dólares")
    assert turn.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
    assert [c["transaction_id"] for c in turn.candidates] == ["TRX-A-DUP2", "TRX-A-DUP1", "TRX-A-080"]


def test_one_named_amount_with_two_matches_opens_the_pick_without_a_reminder(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 35 dólares")
    second = orchestrator.handle_message(owner_session, cid, "1")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION" and "cargos que mencionó" not in second.reply


@pytest.mark.parametrize("report, reason_code", [
    ("Me robaron la tarjeta y no reconozco un cargo de 80 dólares en Oxxo", "STOLEN_CARD_CLAIM"),
    ("No reconozco tres cargos de mi tarjeta: 80, 120 y 850 dólares", "MULTI_CHARGE_FRAUD"),
])
def test_the_lock_audit_records_why_the_card_was_locked(orchestrator, owner_session, ops_store, report, reason_code):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, report)
    assert orchestrator.handle_message(owner_session, cid, "Sí").lock_status == "locked"
    [lock] = [a for a in ops_store.list_audit(conversation_id=cid) if a["action"] == "LOCK_CARD"]
    assert lock["details"].get("reason_code") == reason_code


def test_statement_request_without_dispute_language_still_abstains(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Necesito descargar el extracto de mayo en PDF")
    assert turn.policy_outcome == "SAFE_POLICY_ABSTENTION" and turn.escalation_reason == "OUT_OF_SCOPE_INTENT"
    assert "saldos y extractos" in turn.reply and ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []


@pytest.mark.parametrize("text", ["Pedí el extracto dos veces y todavía no me llega", "Não fiz o download do extrato, podem enviar?",
                                  "No reconozco mi saldo de 80 dólares"])
def test_statement_request_with_a_loose_dispute_word_opens_no_case(orchestrator, other_session, ops_store, text):
    cid = start(orchestrator, other_session)
    turn = orchestrator.handle_message(other_session, cid, text)
    assert turn.policy_outcome == "SAFE_POLICY_ABSTENTION" and turn.escalation_reason == "OUT_OF_SCOPE_INTENT"
    assert ops_store.list_cases(customer_id="CLI-FIX-OTHER") == []


@pytest.mark.parametrize("days_before_today, candidate", [(91, True), (90, False)])
def test_ops_cases_count_as_complaints_like_the_postgres_view(orchestrator, owner_session, ops_store, days_before_today, candidate):
    """ops.v_customer_policy_facts counts ops cases created on or after the business day minus 90 days; so must the DuckDB path."""
    earlier = ops_store.insert_case(
        conversation_id=None, customer_id="CLI-FIX-OWNER", transaction_id="TRX-A-120", product_id="PRD-CARD-1",
        case_values={"case_type": "Claim", "category": "Transactions", "subcategory": "Cargo no reconocido",
                     "reception_channel": "App", "status": "Closed"},
        claimed_amount=120.0, currency="USD", amount_usd=120.0, cited_clauses=["POL-AUT-INTAKE"],
        provisional_credit_candidate=False, provisional_credit_amount_usd=0.0)
    ops_store._run("UPDATE ops_dispute_cases SET created_at = ? WHERE case_id = ?",
                   [datetime(2026, 6, 17) - timedelta(days=days_before_today), earlier])
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert ops_store.get_case(turn.case_id)["provisional_credit_candidate"] is candidate


def test_ambiguous_amount_asks_then_selection_opens_case(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "Tenho uma cobrança estranha de 35 dólares")
    assert first.policy_outcome == "CLARIFICATION_REQUIRED"
    assert first.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
    assert first.state == "awaiting_clarification"
    assert [c["transaction_id"] for c in first.candidates] == ["TRX-A-DUP2", "TRX-A-DUP1"]
    assert "1)" in first.reply and "2)" in first.reply
    second = orchestrator.handle_message(owner_session, cid, "2")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(second.case_id)["transaction_id"] == "TRX-A-DUP1"


@pytest.mark.parametrize("reply", ["Es la opción 2, gracias", "Quiero el número 2."])
def test_option_reply_in_a_sentence_selects_the_listed_charge(orchestrator, owner_session, ops_store, reply):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "Me llegó un cobro raro de 35 dólares")
    assert first.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
    second = orchestrator.handle_message(owner_session, cid, reply)
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(second.case_id)["transaction_id"] == first.candidates[1]["transaction_id"]


def test_no_hints_lists_recent_charges(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Hay un cargo que no reconozco")
    assert turn.policy_outcome == "CLARIFICATION_REQUIRED"
    assert len(turn.candidates) == 5


@pytest.mark.parametrize("text", ["Hola, buenas noches, tengo una consulta", "Esqueci a senha do cartão, podem me ajudar?"])
def test_first_turn_without_dispute_signal_never_picks_the_only_charge(orchestrator, other_session, ops_store, text):
    cid = start(orchestrator, other_session)
    turn = orchestrator.handle_message(other_session, cid, text)
    assert turn.policy_outcome == "CLARIFICATION_REQUIRED" and turn.clarification_reason == "NO_CANDIDATE_CHARGE"
    assert [c["transaction_id"] for c in turn.candidates] == ["TRX-B-050"]
    assert ops_store.list_cases(customer_id="CLI-FIX-OTHER") == [] and turn.handoff_id is None


def test_listed_single_charge_is_picked_by_the_clarification_answer(orchestrator, other_session, ops_store):
    cid = start(orchestrator, other_session)
    first = orchestrator.handle_message(other_session, cid, "Hola, necesito ayuda con algo")
    assert first.state == "awaiting_clarification"
    second = orchestrator.handle_message(other_session, cid, "el de Oxxo")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(second.case_id)["transaction_id"] == "TRX-B-050"


def test_dispute_language_without_hints_still_takes_the_only_charge(orchestrator, other_session, ops_store):
    cid = start(orchestrator, other_session)
    turn = orchestrator.handle_message(other_session, cid, "Hay un cargo que no reconozco en mi tarjeta")
    assert turn.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert ops_store.get_case(turn.case_id)["transaction_id"] == "TRX-B-050"


@pytest.mark.parametrize("first, reply", [("Hola, necesito ayuda con algo", "gracias, nada más"), ("Oi, tudo bem? tenho uma dúvida", "ok")])
def test_a_reply_that_names_no_charge_never_picks_the_only_listed_one(orchestrator, other_session, ops_store, first, reply):
    cid = start(orchestrator, other_session)
    assert orchestrator.handle_message(other_session, cid, first).clarification_reason == "NO_CANDIDATE_CHARGE"
    second = orchestrator.handle_message(other_session, cid, reply)
    assert second.policy_outcome == "CLARIFICATION_REQUIRED" and second.state == "awaiting_clarification"
    assert ops_store.list_cases(customer_id="CLI-FIX-OTHER") == []


def test_a_reply_that_disputes_the_only_listed_charge_opens_the_case(orchestrator, other_session, ops_store):
    cid = start(orchestrator, other_session)
    orchestrator.handle_message(other_session, cid, "Hola, necesito ayuda con algo")
    turn = orchestrator.handle_message(other_session, cid, "No reconozco ese cargo")
    assert turn.policy_outcome == "AUTONOMOUS_RESOLUTION" and ops_store.get_case(turn.case_id)["transaction_id"] == "TRX-B-050"


def test_two_failed_clarifications_go_to_a_human(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 999 dólares")
    orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 998 dólares")
    third = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 997 dólares")
    assert third.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert third.escalation_reason == "UNRESOLVED_AFTER_CLARIFICATIONS"
    assert third.handoff_id and ops_store.get_handoff(third.handoff_id)["status"] == "open"


def test_high_value_charge_creates_handoff_packet(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 850 dólares en Super Ahorro")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert turn.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    assert turn.case_id is None and turn.handoff_id
    packet = ops_store.get_handoff(turn.handoff_id)["packet"]
    assert packet["applicable_policy_clauses"] == ["POL-DISP-TYPE", "POL-WIN-60", "POL-ESC-500"]
    assert packet["triggering_transaction"]["transaction_id"] == "TRX-A-850"
    assert any("within the 60-day window" in f for f in packet["verified_facts"])
    assert packet["customer_request"].startswith("No reconozco")
    assert turn.state == "escalated"


def test_charge_without_usd_value_goes_to_a_human_without_a_case(orchestrator, owner_session, ops_store, bank_fixture_db):
    import duckdb
    con = duckdb.connect(bank_fixture_db)
    con.execute("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id,
        transaction_type, amount, currency, amount_usd, merchant_name, transaction_status, is_within_60_days, days_since_transaction)
        VALUES ('TRX-A-NOUSD', TIMESTAMP '2026-06-15 16:00:00', DATE '2026-06-15', 'CLI-FIX-OWNER', 'PRD-CARD-1', 'Purchase',
                185000.0, 'COP', NULL, 'Mercado Rio', 'Approved', true, 2)""")
    con.close()
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cobro de 185.000 pesos en Mercado Rio")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "DATA_GAP_AMOUNT_USD"
    assert turn.handoff_id and ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []
    assert "Número de caso" not in turn.reply
    trigger = ops_store.get_handoff(turn.handoff_id)["packet"]["triggering_transaction"]
    assert trigger["transaction_id"] == "TRX-A-NOUSD" and trigger["amount_usd"] is None  # unknown, never a made-up 0.0


@pytest.mark.parametrize("method", ["get_customer_profile", "search_customer_transactions"])
def test_bank_read_timeout_hands_off_without_confirming(orchestrator, owner_session, ops_store, monkeypatch, method):
    monkeypatch.setattr(orchestrator.gateway, method, raising(TimeoutError(f"simulated {method}")))
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Hay un cargo de 80 dólares en Oxxo que no hice")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "SYSTEM_OF_RECORD_UNAVAILABLE"
    assert turn.state == "escalated" and turn.handoff_id and turn.handoff_id in turn.reply
    assert ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []
    assert "Número de caso" not in turn.reply and "bloque" not in turn.reply


def test_lock_timeout_after_yes_is_reported_pending_not_done(orchestrator, owner_session, ops_store, monkeypatch):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y hay un cargo de 80 dólares en Oxxo que no hice")
    assert first.state == "awaiting_lock_confirmation"
    monkeypatch.setattr(orchestrator.gateway, "execute_lock_card", raising(TimeoutError("simulated execute_lock_card")))
    second = orchestrator.handle_message(owner_session, cid, "Sí")
    assert second.lock_status == "pending" and second.state == "escalated" and "quedó bloqueada" not in second.reply
    assert [h["escalation_reason"] for h in ops_store.list_handoffs() if h["conversation_id"] == cid] == ["ACTION_VERIFICATION_FAILED"]


def test_card_listing_timeout_keeps_the_verified_case_number(orchestrator, owner_session, ops_store, monkeypatch):
    monkeypatch.setattr(orchestrator.gateway, "list_customer_cards", raising(TimeoutError("simulated list_customer_cards")))
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y hay un cargo de 80 dólares en Oxxo que no hice")
    assert turn.case_id and turn.case_id in turn.reply and turn.lock_offer is None and turn.state == "closed"
    assert any(a["action"] == "LOCK_NOT_OFFERED" and a["details"]["why"] == "system of record unavailable"
               for a in ops_store.list_audit(conversation_id=cid))


def test_a_programming_error_is_not_mistaken_for_an_outage(orchestrator, owner_session, monkeypatch):
    monkeypatch.setattr(orchestrator.gateway, "search_customer_transactions", raising(KeyError("merchant_name")))
    cid = start(orchestrator, owner_session)
    with pytest.raises(KeyError):
        orchestrator.handle_message(owner_session, cid, "Hay un cargo de 80 dólares en Oxxo que no hice")


def test_out_of_window_charge_abstains_without_case(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 60 dólares del 19 de marzo en Cine Premium")
    assert turn.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert turn.escalation_reason == "OUT_OF_POLICY_WINDOW"
    assert "60 días" in turn.reply
    assert ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []


def test_declined_charge_is_not_disputable(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 45 dólares en Farmacia Central")
    assert turn.escalation_reason == "NOT_DISPUTABLE_CHARGE"
    assert turn.case_id is None


def test_loan_question_abstains_naming_the_category(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Quiero pedir un préstamo para mi casa")
    assert turn.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert turn.escalation_reason == "OUT_OF_SCOPE_INTENT"
    assert "préstamos" in turn.reply


def test_legal_citation_escalates_before_identifying_a_charge(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Si no me resuelven voy a la CONDUSEF")
    assert turn.escalation_reason == "REGULATOR_OR_LEGAL_CITING"
    assert turn.cited_clauses == ["POL-ESC-LEGAL"]


@pytest.mark.parametrize("answer, expected_status, expected_product_status", [
    ("Sí, bloquéenla por favor", "locked", "Blocked"),
    ("No, todavía no", "refused", "Active"),
])
def test_stolen_card_offers_lock_and_customer_decides(orchestrator, owner_session, ops_store, bank_fixture_db, answer,
                                                       expected_status, expected_product_status):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y no reconozco un cargo de 80 dólares en Oxxo")
    assert first.case_id and first.lock_offer["product_id"] == "PRD-CARD-1"
    assert first.lock_offer["required_authentication"] == "SESSION_AND_CUSTOMER_CONFIRMATION"
    assert first.state == "awaiting_lock_confirmation"
    second = orchestrator.handle_message(owner_session, cid, answer)
    assert second.lock_status == expected_status
    assert second.state == "closed"
    assert fetch(bank_fixture_db, "SELECT product_status FROM silver_products WHERE product_id = ?", ["PRD-CARD-1"]) == [(expected_product_status,)]
    [lock] = ops_store.list_locks(conversation_id=cid)
    assert lock["status"] == expected_status
    if expected_status == "locked":
        assert lock["verified"] is True
        assert any(a["action"] == "LOCK_CARD" and a["verified"] for a in ops_store.list_audit(conversation_id=cid))


def test_lock_confirmation_unclear_answer_asks_again(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y no reconozco un cargo de 80 dólares en Oxxo")
    turn = orchestrator.handle_message(owner_session, cid, "qué significa eso?")
    assert turn.state == "awaiting_lock_confirmation"
    assert turn.lock_status == "offered"


@pytest.mark.parametrize("answer, lock_status", [("Sí, por favor", "locked"), ("No, gracias", "refused")])
def test_lost_card_report_offers_the_lock_before_asking_which_charge(orchestrator, owner_session, ops_store, answer, lock_status):
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "Anteayer extravié la tarjeta de crédito")
    assert first.policy_outcome == "CLARIFICATION_REQUIRED" and first.state == "awaiting_lock_confirmation"
    assert first.lock_offer["product_id"] == "PRD-CARD-1" and first.case_id is None
    second = orchestrator.handle_message(owner_session, cid, answer)
    assert second.lock_status == lock_status and second.state == "awaiting_clarification" and len(second.candidates) == 5
    third = orchestrator.handle_message(owner_session, cid, "3")
    assert [c["transaction_id"] for c in ops_store.list_cases(customer_id="CLI-FIX-OWNER")] == [second.candidates[2]["transaction_id"]]
    assert third.case_id


def test_yes_to_the_lock_never_opens_a_case_on_a_listed_charge(orchestrator, other_session, ops_store):
    cid = start(orchestrator, other_session)
    first = orchestrator.handle_message(other_session, cid, "Perdi o cartão ontem no ônibus")
    assert first.state == "awaiting_lock_confirmation" and first.case_id is None
    second = orchestrator.handle_message(other_session, cid, "sim")
    assert second.lock_status == "locked" and second.state == "awaiting_clarification"
    assert [c["transaction_id"] for c in second.candidates] == ["TRX-B-050"]
    assert ops_store.list_cases(customer_id="CLI-FIX-OTHER") == []
    third = orchestrator.handle_message(other_session, cid, "obrigado")
    assert third.state == "awaiting_clarification" and ops_store.list_cases(customer_id="CLI-FIX-OTHER") == []


def test_lock_answer_after_an_out_of_scope_turn_still_closes(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    assert orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 35 dólares").state == "awaiting_clarification"
    second = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta, quiero una nueva tarjeta")
    assert second.policy_outcome == "SAFE_POLICY_ABSTENTION" and second.state == "awaiting_lock_confirmation"
    third = orchestrator.handle_message(owner_session, cid, "No, gracias")
    assert third.lock_status == "refused" and third.state == "closed"  # no earlier clarification comes back


def test_lock_first_resumes_after_an_earlier_escalation_in_the_same_conversation(orchestrator, owner_session):
    cid = start(orchestrator, owner_session)
    assert orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 850 dólares en Super Ahorro").state == "escalated"
    assert orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta").state == "awaiting_lock_confirmation"
    third = orchestrator.handle_message(owner_session, cid, "Sí")
    assert third.lock_status == "locked" and third.state == "awaiting_clarification" and len(third.candidates) == 5


def test_an_outage_while_resuming_hands_the_charge_question_to_a_human(orchestrator, owner_session, ops_store, monkeypatch):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    monkeypatch.setattr(orchestrator.gateway, "search_customer_transactions", raising(TimeoutError("simulated search")))
    second = orchestrator.handle_message(owner_session, cid, "Sí")
    assert second.lock_status == "locked" and second.state == "escalated" and second.handoff_id in second.reply
    handoff = ops_store.get_handoff(second.handoff_id)
    assert handoff["escalation_reason"] == "SYSTEM_OF_RECORD_UNAVAILABLE" and len(handoff["packet"]["pending_clarification"]["candidate_ids"]) == 5
    packet = handoff["packet"]  # what the console shows the agent: the request, the facts and the clauses
    assert packet["customer_request"] == "Perdí la tarjeta" and packet["applicable_policy_clauses"] == ["POL-CLARIFY", "POL-AUT-LOCK"]
    assert any("locked" in fact for fact in packet["verified_facts"])


def test_a_failed_lock_hands_over_the_pending_charge_question(orchestrator, owner_session, ops_store, monkeypatch):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    listed = ops_store.get_conversation(cid)["candidate_ids"]
    monkeypatch.setattr(orchestrator.gateway, "execute_lock_card", raising(ActionVerificationError("simulated read-back")))
    second = orchestrator.handle_message(owner_session, cid, "Sí")
    assert second.lock_status == "pending" and second.state == "escalated"
    [handoff] = [h for h in ops_store.list_handoffs() if h["conversation_id"] == cid]
    assert handoff["packet"]["pending_clarification"]["candidate_ids"] == listed


def test_a_charge_told_at_the_lock_question_is_not_a_refusal(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    second = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert second.lock_status == "offered" and second.state == "awaiting_lock_confirmation"
    assert [lk["status"] for lk in ops_store.list_locks(conversation_id=cid)] == ["offered"]


def test_a_refusal_that_also_tells_the_charge_is_still_a_refusal(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    assert orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y veo compras que no hice").state == "awaiting_lock_confirmation"
    second = orchestrator.handle_message(owner_session, cid, "No, no la bloqueen, las compras no las hice yo")
    assert second.lock_status == "refused" and second.state == "awaiting_clarification" and second.candidates


def test_a_failed_lock_after_an_earlier_escalation_gets_its_own_handoff(orchestrator, owner_session, ops_store, monkeypatch):
    cid = start(orchestrator, owner_session)
    assert orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 850 dólares en Super Ahorro").state == "escalated"
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    monkeypatch.setattr(orchestrator.gateway, "execute_lock_card", raising(ActionVerificationError("simulated read-back")))
    third = orchestrator.handle_message(owner_session, cid, "Sí")
    assert third.lock_status == "pending" and third.handoff_id  # the customer hears a specialist will finish it: one must exist
    handoff = ops_store.get_handoff(third.handoff_id)
    assert handoff["escalation_reason"] == "ACTION_VERIFICATION_FAILED"
    assert handoff["packet"]["customer_request"] == "Perdí la tarjeta" and handoff["packet"]["applicable_policy_clauses"] == ["POL-AUT-LOCK"]
    assert any(a["action"] == "CREATE_HANDOFF" and a["verified"] and a["details"]["handoff_id"] == third.handoff_id
               for a in ops_store.list_audit(conversation_id=cid))


@pytest.mark.parametrize("answer", ["Si no reconozco la compra, ¿qué pasa?", "Confirmo que no hice esa compra", "¿Qué pasa si la bloqueo?",
                                    "Quero pensar um pouco antes", "Sigo buscándola, un momento", "No fui yo, lo confirmo", "No importa",
                                    "Sim, não quero que usem", "Claro, no quiero perder la tarjeta"])
def test_a_question_or_a_dispute_at_the_lock_question_locks_nothing(orchestrator, owner_session, ops_store, answer):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y veo compras que no hice")
    second = orchestrator.handle_message(owner_session, cid, answer)
    assert second.lock_status == "offered" and [lk["status"] for lk in ops_store.list_locks(conversation_id=cid)] == ["offered"]


def test_a_clear_yes_without_commas_locks_the_card(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    second = orchestrator.handle_message(owner_session, cid, "no hay problema bloquéala")
    assert second.lock_status == "locked" and [lk["status"] for lk in ops_store.list_locks(conversation_id=cid)] == ["locked"]


def test_the_day_of_the_theft_in_a_sentence_of_its_own_picks_no_charge(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta. Fue el 13 de junio. Hay 35 dólares que no reconozco")
    assert turn.policy_outcome == "CLARIFICATION_REQUIRED" and ops_store.list_cases(customer_id="CLI-FIX-OWNER") == []


@pytest.mark.parametrize("answer", ["No lo reconozco, es un cargo de 80 dólares en Oxxo", "No sé qué es ese cargo de 80 dólares"])
def test_a_charge_told_after_a_plain_no_is_asked_again(orchestrator, owner_session, ops_store, answer):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    second = orchestrator.handle_message(owner_session, cid, answer)
    assert second.lock_status == "offered" and second.state == "awaiting_lock_confirmation"


def test_not_wanting_the_lock_is_a_refusal(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    assert orchestrator.handle_message(owner_session, cid, "Roubaram meu cartão").state == "awaiting_lock_confirmation"
    second = orchestrator.handle_message(owner_session, cid, "Não quero bloquear")
    assert second.lock_status == "refused" and [lk["status"] for lk in ops_store.list_locks(conversation_id=cid)] == ["refused"]


def test_the_outage_handoff_names_the_report_that_led_to_the_lock_offer(orchestrator, owner_session, ops_store, monkeypatch):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta")
    assert orchestrator.handle_message(owner_session, cid, "mmm espere, déjeme pensar").state == "awaiting_lock_confirmation"
    monkeypatch.setattr(orchestrator.gateway, "search_customer_transactions", raising(TimeoutError("simulated search")))
    third = orchestrator.handle_message(owner_session, cid, "Sí")
    assert ops_store.get_handoff(third.handoff_id)["packet"]["customer_request"] == "Perdí la tarjeta"


def test_other_customer_cannot_touch_the_conversation(orchestrator, owner_session, other_session, ops_store):
    cid = start(orchestrator, owner_session)
    with pytest.raises(UnauthorizedAccessError):
        orchestrator.handle_message(other_session, cid, "No reconozco un cargo de 80 dólares")
    with pytest.raises(UnauthorizedAccessError):
        orchestrator.get_conversation(other_session, cid)
    assert any(a["action"] == "CONVERSATION_ACCESS_DENIED" for a in ops_store.list_audit(conversation_id=cid))


def test_search_never_returns_other_customers_charges(orchestrator, other_session):
    cid = start(orchestrator, other_session)
    turn = orchestrator.handle_message(other_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert turn.policy_outcome == "CLARIFICATION_REQUIRED"
    assert turn.clarification_reason == "NO_CANDIDATE_CHARGE"


def test_unknown_customer_profile_escalates_with_the_gap_named(bank_fixture_db, ops_store):
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    from tests.conftest import make_session
    orch = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store)
    ghost = make_session("CLI-FIX-GHOST")
    cid = start(orch, ghost)
    turn = orch.handle_message(ghost, cid, "No reconozco un cargo de 80 dólares")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert turn.escalation_reason == "DATA_GAP_CUSTOMER_PROFILE"
    assert turn.handoff_id


def test_second_case_within_48h_counts_toward_multi_charge(orchestrator, owner_session, ops_store):
    cid = start(orchestrator, owner_session)
    orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    orchestrator.handle_message(owner_session, cid, "Tampoco reconozco un cargo de 120 dólares en Cine Premium")
    third = orchestrator.handle_message(owner_session, cid, "Y otro de 35 dólares en Tienda Sur")
    assert third.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert third.escalation_reason == "MULTIPLE_CHARGES_48H"
    assert third.lock_offer and third.lock_offer["reason"] == "MULTI_CHARGE_FRAUD"
    assert len(ops_store.list_cases(customer_id="CLI-FIX-OWNER")) == 2


def test_same_charge_is_not_opened_twice(orchestrator, owner_session, ops_store):
    """Idempotency: a charge with an open case is not registered again; the customer gets the existing case id."""
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    second = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert second.case_id == first.case_id
    assert len(ops_store.list_cases(customer_id="CLI-FIX-OWNER")) == 1
    assert "ya" in second.reply and first.case_id in second.reply
    assert any(a["action"] == "DUPLICATE_CASE_PREVENTED" for a in ops_store.list_audit(conversation_id=cid))


class _FixedRiskScorer:
    """A loaded risk model that scores every charge 0.12 against its own policy threshold."""
    policy_threshold = 0.30

    def __call__(self, matched, history, profile):
        return 0.12, []


def _risk_fact(ops_store, handoff_id):
    facts = ops_store.get_handoff(handoff_id)["packet"]["verified_facts"]
    return [fact for fact in facts if fact.startswith("ML risk score")]


def test_a_handoff_without_a_risk_model_never_reads_as_a_zero_risk(orchestrator, owner_session, ops_store):
    """With no model file the scorer is off: the agent must not read a measured 0.00 against an unused 0.70 threshold."""
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "En el estado de cuenta me sale una compra de 850 dólares en Super Ahorro que no es mía")
    [fact] = _risk_fact(ops_store, turn.handoff_id)
    assert "not scored" in fact and "no risk model" in fact
    assert "0.00" not in fact and "0.70" not in fact


def test_a_handoff_with_a_risk_model_states_the_score_and_its_threshold(bank_fixture_db, ops_store, owner_session):
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, risk_scorer=_FixedRiskScorer())
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "En el estado de cuenta me sale una compra de 850 dólares en Super Ahorro que no es mía")
    assert _risk_fact(ops_store, turn.handoff_id) == ["ML risk score: 0.12 (escalation threshold 0.30)"]


def test_a_handoff_before_any_charge_says_the_risk_was_not_scored(bank_fixture_db, ops_store, owner_session):
    """A legal citation escalates before a charge is identified: the loaded model had nothing to score."""
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, risk_scorer=_FixedRiskScorer())
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Si no me resuelven voy a la CONDUSEF")
    assert turn.escalation_reason == "REGULATOR_OR_LEGAL_CITING"
    [fact] = _risk_fact(ops_store, turn.handoff_id)
    assert "not scored" in fact and "no charge" in fact and "0.00" not in fact


@pytest.mark.parametrize("messages", [
    ["¿Cuántos días tengo para disputar un cargo?"],
    ["Hola", "¿Cuántos días tengo para disputar un cargo?"],
    ["Oi", "Quanto tempo tenho para contestar uma cobrança?"],
])
def test_a_rules_question_never_opens_the_case_of_a_customers_only_charge(orchestrator, other_session, ops_store, messages):
    """A question about the dispute rules names no charge of its own: with the explainer off it asks which charge, it never
    takes the customer's only one."""
    cid = start(orchestrator, other_session)
    for text in messages:
        turn = orchestrator.handle_message(other_session, cid, text)
    assert ops_store.list_cases(customer_id="CLI-FIX-OTHER") == []
    assert turn.case_id is None and turn.policy_outcome == "CLARIFICATION_REQUIRED"


# ------------------------------------------------- which card a preventive lock may take
def add_card(db_path, product_id, product_type="Tarjeta Crédito"):
    """One more active card for the fixture owner (team-generated)."""
    import duckdb
    con = duckdb.connect(db_path)
    try:
        con.execute("INSERT INTO silver_products (product_id, customer_id, product_type, product_status) VALUES (?, 'CLI-FIX-OWNER', ?, 'Active')",
                    [product_id, product_type])
    finally:
        con.close()


def add_account_transfer(db_path, transaction_id="TRX-A-ACC90", amount=90.0, merchant="Tienda Este"):
    """An in-window transfer out of the owner's savings account, so a charge that sits on no card (team-generated)."""
    import duckdb
    con = duckdb.connect(db_path)
    try:
        con.execute("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id,
            product_type, product_status, transaction_type, amount, currency, amount_usd, merchant_name, transaction_status,
            is_within_60_days, days_since_transaction)
            VALUES (?, TIMESTAMP '2026-06-12 15:00:00', DATE '2026-06-12', 'CLI-FIX-OWNER', 'PRD-ACC-1', 'Cuenta Ahorros', 'Active',
                    'Transfer', ?, 'USD', ?, ?, 'Approved', true, 5)""", [transaction_id, amount, amount, merchant])
        con.execute("""INSERT INTO silver_transactions (transaction_id, transaction_date, process_date, product_id, customer_id,
            transaction_type, amount, currency, merchant_name, transaction_status)
            VALUES (?, TIMESTAMP '2026-06-12 15:00:00', DATE '2026-06-12', 'PRD-ACC-1', 'CLI-FIX-OWNER', 'Transfer', ?, 'USD', ?, 'Approved')""",
                    [transaction_id, amount, merchant])
    finally:
        con.close()


@pytest.mark.parametrize("label", ["Unknown", "Unknown Merchant", "Not Applicable"])
def test_a_placeholder_merchant_label_is_never_a_merchant_hint(orchestrator, label):
    """Gold writes a label where a charge has no merchant; a message that happens to contain it names no merchant."""
    from src.understand.keyword_extractor import UnderstandResult
    u = UnderstandResult(language="es", message_lower=f"en mi extracto dice {label.lower()}")
    assert orchestrator._merchant_in_message({"merchant_name_raw": label}, u) is False
    assert orchestrator._merchant_in_message({"merchant_name_raw": "Tienda Este"}, UnderstandResult(language="es", message_lower="un cargo en tienda este")) is True


def owner_product_statuses(db_path):
    return dict(fetch(db_path, "SELECT product_id, product_status FROM silver_products WHERE customer_id = 'CLI-FIX-OWNER'", []))


@pytest.mark.parametrize("message", [
    "Me robaron la tarjeta y no reconozco una transferencia de 90 dólares en Tienda Este",
    "Roubaram meu cartão e não reconheço uma transferência de 90 dólares na Tienda Este",
])
def test_a_stolen_card_claim_never_picks_one_of_several_cards_for_a_charge_on_none(orchestrator, owner_session, ops_store,
                                                                                    bank_fixture_db, message):
    add_card(bank_fixture_db, "PRD-CARD-3")
    add_account_transfer(bank_fixture_db)
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, message)
    assert turn.case_id  # the dispute itself is still opened and verified
    assert turn.lock_offer is None and turn.state == "escalated"
    assert ops_store.list_locks(conversation_id=cid) == []
    assert set(owner_product_statuses(bank_fixture_db).values()) == {"Active"}
    handoff = ops_store.get_handoff(turn.handoff_id)
    assert handoff["escalation_reason"] == "LOCK_CARD_AMBIGUOUS"
    assert sorted(handoff["packet"]["card_lock"]["candidate_products"]) == ["PRD-CARD-1", "PRD-CARD-3"]
    assert turn.handoff_id in turn.reply and "especialista" in turn.reply
    audit = ops_store.list_audit(conversation_id=cid)
    assert any(a["action"] == "CREATE_HANDOFF" and a["verified"] for a in audit)
    assert any(a["action"] == "LOCK_NOT_OFFERED" and a["details"]["why"] == "several active cards, none tied to the charge" for a in audit)


def test_a_lost_card_report_with_several_cards_asks_for_the_charge_and_leaves_the_card_to_a_specialist(
        orchestrator, owner_session, ops_store, bank_fixture_db):
    add_card(bank_fixture_db, "PRD-CARD-3")
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Anteayer extravié la tarjeta de crédito")
    assert turn.policy_outcome == "CLARIFICATION_REQUIRED" and turn.state == "awaiting_clarification"
    assert turn.lock_offer is None and ops_store.list_locks(conversation_id=cid) == []
    assert len(turn.candidates) == 5  # the charge question goes on as if no lock had been recommended
    assert ops_store.get_handoff(turn.handoff_id)["escalation_reason"] == "LOCK_CARD_AMBIGUOUS"
    assert turn.handoff_id in turn.reply and "especialista" in turn.reply


def test_a_charge_on_one_of_several_cards_offers_that_card(orchestrator, owner_session, bank_fixture_db):
    add_card(bank_fixture_db, "PRD-CARD-0")  # sorts first by id, so a first-card pick would take the wrong one
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y no reconozco un cargo de 80 dólares en Oxxo")
    assert turn.lock_offer["product_id"] == "PRD-CARD-1" and turn.handoff_id is None


def test_a_charge_on_no_card_offers_the_only_active_card(orchestrator, owner_session, bank_fixture_db):
    add_account_transfer(bank_fixture_db)
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "Me robaron la tarjeta y no reconozco una transferencia de 90 dólares en Tienda Este")
    assert turn.lock_offer["product_id"] == "PRD-CARD-1"  # one active card: no doubt about which one was stolen


# ------------------------------------------------- sibling charges: same card, merchant and process day (TQ-039)
def add_card_charge(db_path, transaction_id, when, amount, merchant, product_id="PRD-CARD-1", status="Approved"):
    """One more in-window purchase of the fixture owner (team-generated). Process day = date(when - 6 h)."""
    import duckdb
    moment = datetime.fromisoformat(when)
    process_day = (moment - timedelta(hours=6)).date()
    con = duckdb.connect(db_path)
    try:
        con.execute("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id,
            product_type, product_status, transaction_type, amount, currency, amount_usd, merchant_name, transaction_status,
            is_within_60_days, days_since_transaction)
            VALUES (?, ?, ?, 'CLI-FIX-OWNER', ?, 'Tarjeta Crédito', 'Active', 'Purchase', ?, 'USD', ?, ?, ?, true, ?)""",
                    [transaction_id, moment, process_day, product_id, amount, amount, merchant, status,
                     (datetime(2026, 6, 17).date() - process_day).days])
    finally:
        con.close()


def sibling_audit(ops_store, cid):
    return [a for a in ops_store.list_audit(conversation_id=cid) if a["action"] == "SIBLING_CHARGES_LISTED"]


@pytest.mark.parametrize("message, also", [
    ("No reconozco un cargo de 80 dólares en Oxxo", "Además"),
    ("Não reconheço uma compra de 80 dólares no Oxxo", "Além disso"),
])
def test_sibling_charges_are_told_once_the_case_is_open_and_never_counted(orchestrator, owner_session, ops_store, bank_fixture_db,
                                                                         message, also):
    """TRX-A-080 is on PRD-CARD-1 at Oxxo on process day 9-Jun. Two more Oxxo purchases of that card and night, one after
    midnight, are told to the customer with the case number; nobody disputed them, so they open no case and POL-ESC-MULTI stays out."""
    add_card_charge(bank_fixture_db, "TRX-A-SIB1", "2026-06-09 23:40:00", 22.0, "Oxxo")
    add_card_charge(bank_fixture_db, "TRX-A-SIB2", "2026-06-10 04:50:00", 61.5, "Oxxo")
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, message)
    assert turn.policy_outcome == "AUTONOMOUS_RESOLUTION" and turn.state == "closed" and turn.lock_offer is None
    assert [c["transaction_id"] for c in ops_store.list_cases(customer_id="CLI-FIX-OWNER")] == ["TRX-A-080"]
    assert also in turn.reply and "Oxxo" in turn.reply and "22.00 USD" in turn.reply and "61.50 USD" in turn.reply
    assert turn.reply.index(turn.case_id) < turn.reply.index(also)  # the verified case first, the other charges after
    listed = sibling_audit(ops_store, cid)
    assert len(listed) == 1 and listed[0]["details"]["transaction_id"] == "TRX-A-080"
    assert sorted(listed[0]["details"]["sibling_ids"]) == ["TRX-A-SIB1", "TRX-A-SIB2"]


def test_sibling_charges_share_the_card_the_merchant_the_process_day_and_are_disputable(orchestrator, owner_session, ops_store,
                                                                                        bank_fixture_db):
    add_card(bank_fixture_db, "PRD-CARD-3")
    add_card_charge(bank_fixture_db, "TRX-A-SIB1", "2026-06-09 23:40:00", 22.0, "Oxxo")
    add_card_charge(bank_fixture_db, "TRX-A-X1", "2026-06-09 20:00:00", 23.0, "Farmacia Central")  # another merchant
    add_card_charge(bank_fixture_db, "TRX-A-X2", "2026-06-10 12:00:00", 24.0, "Oxxo")  # the next process day
    add_card_charge(bank_fixture_db, "TRX-A-X3", "2026-06-09 21:00:00", 25.0, "Oxxo", status="Declined")  # not disputable
    add_card_charge(bank_fixture_db, "TRX-A-X4", "2026-06-09 22:00:00", 26.0, "Oxxo", product_id="PRD-CARD-3")  # another card
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert turn.case_id and "22.00 USD" in turn.reply
    assert not any(f"{amount}.00 USD" in turn.reply for amount in (23, 24, 25, 26))
    assert sibling_audit(ops_store, cid)[0]["details"]["sibling_ids"] == ["TRX-A-SIB1"]


def test_a_sibling_charge_with_an_open_case_is_not_told_again(orchestrator, owner_session, ops_store, bank_fixture_db):
    add_card_charge(bank_fixture_db, "TRX-A-SIB1", "2026-06-09 23:40:00", 22.0, "Oxxo")
    cid = start(orchestrator, owner_session)
    first = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert "22.00 USD" in first.reply
    second = orchestrator.handle_message(owner_session, cid, "Tampoco reconozco un cargo de 22 dólares en Oxxo")
    assert second.policy_outcome == "AUTONOMOUS_RESOLUTION" and second.case_id != first.case_id
    assert "Además" not in second.reply and "80.00 USD" not in second.reply  # its only sibling already has a case
    assert len(sibling_audit(ops_store, cid)) == 1


@pytest.mark.parametrize("label", ["Unknown Merchant", "Not Applicable"])
def test_charges_without_a_merchant_on_record_are_no_siblings(orchestrator, owner_session, ops_store, bank_fixture_db, label):
    """Most bank rows carry no merchant (gold writes Not Applicable or Unknown Merchant): two of them are not one merchant."""
    add_card_charge(bank_fixture_db, "TRX-A-UNK1", "2026-06-16 10:00:00", 31.0, label)
    add_card_charge(bank_fixture_db, "TRX-A-UNK2", "2026-06-16 11:00:00", 32.0, label)
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 31 dólares")
    assert turn.case_id and ops_store.get_case(turn.case_id)["transaction_id"] == "TRX-A-UNK1"
    assert "Además" not in turn.reply and "32.00 USD" not in turn.reply and sibling_audit(ops_store, cid) == []


def test_a_handoff_states_the_sibling_charges_and_the_reply_does_not(orchestrator, owner_session, ops_store, bank_fixture_db):
    """An escalated turn leaves the other charges to the specialist: a verified fact in the packet, nothing more in the reply,
    and the 48-hour count still holds the one disputed charge."""
    add_card_charge(bank_fixture_db, "TRX-A-SIB3", "2026-06-14 21:10:00", 40.0, "Super Ahorro")
    cid = start(orchestrator, owner_session)
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 850 dólares en Super Ahorro")
    assert turn.policy_outcome == "MANDATORY_HITL_ESCALATION" and turn.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    facts = ops_store.get_handoff(turn.handoff_id)["packet"]["verified_facts"]
    assert "1 other undisputed charge(s) on the same product, merchant and process day: TRX-A-SIB3" in facts
    assert "1 distinct charge(s) disputed within 48 hours" in facts
    assert "Además" not in turn.reply and "40.00 USD" not in turn.reply and sibling_audit(ops_store, cid) == []


# ------------------------------------------------------------ language of the conversation (TQ-042)
@pytest.mark.parametrize("current, text, shift", [
    ("es", "Olá, não reconheço uma cobrança de 120 dólares", "switch"),
    ("pt", "No reconozco un cargo de mi tarjeta, quiero disputarlo", "switch"),
    ("pt", "É a de 157.118,47 pesos", "keep"),   # "pesos" holds one weak Spanish marker: no doubt
    ("es", "1", "keep"), ("es", "Sí", "keep"), ("pt", "Sim, pode bloquear", "keep"),
    ("es", "No reconozco el cargo de mi tarjeta, não fui eu que fiz essa compra", "ask"),  # both languages, neither dominates
    ("es", "Quiero disputar el cargo de ayer en mi tarjeta", "keep"),
])
def test_a_message_moves_the_language_only_on_clear_evidence(current, text, shift):
    from src.understand.keyword_extractor import KeywordIntentExtractor
    assert KeywordIntentExtractor.language_shift(text.lower(), current) == shift


@pytest.mark.parametrize("text, language", [
    ("português", "pt"), ("Em português, por favor", "pt"), ("Portugues", "pt"), ("español", "es"), ("en español por favor", "es"),
    ("Espanhol", "es"), ("castellano", "es"),
    ("No reconozco un cargo en español", None), ("Hola", None), ("1", None),
])
def test_a_message_that_only_names_a_language_is_a_language_choice(text, language):
    from src.understand.keyword_extractor import KeywordIntentExtractor
    assert KeywordIntentExtractor.language_choice(text) == language


def test_a_mixed_message_is_handled_and_the_customer_is_asked_which_language(orchestrator, owner_session, ops_store):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    orchestrator.handle_message(owner_session, cid, "Hola")
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco el cargo de mi tarjeta de 120 dólares en Cine Premium, não fui eu que fiz essa compra")
    assert turn.case_id and turn.language == "es"  # the turn is not held back by the doubt
    assert turn.reply.endswith('Se preferir continuar em português, escreva "português".')
    chosen = orchestrator.handle_message(owner_session, cid, "português")
    assert chosen.language == "pt" and chosen.policy_outcome is None and chosen.reply.startswith("Pronto, continuamos em português")
    assert ops_store.get_conversation(cid)["language"] == "pt"
    assert [a["action"] for a in ops_store.list_audit(conversation_id=cid)].count("LANGUAGE_CHANGED") == 1


def test_a_language_choice_keeps_a_pending_lock_question_pending(orchestrator, owner_session, ops_store):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    assert orchestrator.handle_message(owner_session, cid, "Perdí la tarjeta").state == "awaiting_lock_confirmation"
    chosen = orchestrator.handle_message(owner_session, cid, "Em português, por favor")
    assert chosen.state == "awaiting_lock_confirmation" and chosen.language == "pt"
    assert ops_store.list_locks(conversation_id=cid) == []
    done = orchestrator.handle_message(owner_session, cid, "Sim")
    assert done.lock_status == "verified" and done.language == "pt"


def test_a_clear_first_message_gets_no_language_question(orchestrator, owner_session):
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 120 dólares en Cine Premium")
    assert "português" not in turn.reply and "español" not in turn.reply
