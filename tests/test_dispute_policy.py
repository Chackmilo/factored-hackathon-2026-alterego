"""
Tests of the dispute policy engine, one clause id per test name (docs/specs/dispute-policy-v2.3.md).
Run: uv run pytest tests/test_dispute_policy.py -q
"""
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from src.rules.dispute_policy import (
    OUT_OF_SCOPE_CATEGORIES,
    DisputePolicyEngine,
    DisputePolicyInput,
)

TODAY = date(2026, 6, 17)


def make_input(**overrides) -> DisputePolicyInput:
    """Base case of the acceptance criteria: Plus customer, eligible $100 Purchase of 2026-06-10."""
    base = dict(
        customer_id="CLI-TEST-BASE",
        customer_segment="Plus",
        customer_country="Colombia",
        account_age_days=300,
        complaints_last_90d=0,
        transaction_id="TRX-BASE",
        transaction_date=date(2026, 6, 10),
        transaction_amount=100.0,
        transaction_currency="USD",
        amount_usd=100.0,
        transaction_type="Purchase",
        transaction_status="Approved",
        current_date=TODAY,
    )
    base.update(overrides)
    return DisputePolicyInput(**base)


def evaluate(**overrides):
    return DisputePolicyEngine.evaluate(make_input(**overrides))


def test_pol_win_60_out_of_window_abstention():
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
        transaction_type="Purchase",
        transaction_status="Approved",
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
def test_pol_win_60_counts_bank_process_day(transaction_date, expected_outcome):
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
        transaction_type="Purchase",
        transaction_status="Approved",
        amount_usd=100.0,
        current_date=date(2026, 6, 17)
    )
    assert DisputePolicyEngine.evaluate(p_input).policy_outcome == expected_outcome

def test_pol_aut_150_customer_never_hears_credit():
    """POL-AUT-150 is a candidate flag a human approves; the customer hears 'registered and under review', never 'credit'."""
    decision = evaluate(account_age_days=250, transaction_amount=120.0, amount_usd=120.0)
    assert decision.is_eligible
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.provisional_credit_candidate is True
    assert decision.provisional_credit_amount_usd == 120.0
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE", "POL-AUT-150"]
    assert decision.action_required == "OPEN_DISPUTE_ONLY"
    assert "crédito" not in decision.explanation_es.lower()
    assert "crédito" not in decision.explanation_pt.lower()
    assert "registrada" in decision.explanation_es and "registrada" in decision.explanation_pt


def test_pol_aut_150_exactly_150_is_candidate():
    decision = evaluate(account_age_days=250, transaction_amount=150.0, amount_usd=150.0)
    assert decision.provisional_credit_candidate is True
    assert decision.provisional_credit_amount_usd == 150.0
    assert decision.action_required == "OPEN_DISPUTE_ONLY"
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE", "POL-AUT-150"]
    assert decision.case_values["status"] == "Open"


@pytest.mark.parametrize("age, candidate", [(180, False), (181, True)])
def test_pol_aut_150_account_age_boundary(age, candidate):
    assert evaluate(account_age_days=age).provisional_credit_candidate is candidate


@pytest.mark.parametrize("overrides", [dict(customer_segment="Basic"), dict(customer_segment="Student"), dict(complaints_last_90d=1)])
def test_pol_aut_150_segment_and_complaints_gate(overrides):
    decision = evaluate(**overrides)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.provisional_credit_candidate is False
    assert "POL-AUT-150" not in decision.cited_clauses


def test_pol_aut_150_currency_matrix():
    """608,000 COP at the 2026-06-17 rate is 149.95 USD: a candidate, with the USD amount recorded."""
    decision = evaluate(transaction_amount=608_000.0, transaction_currency="COP", amount_usd=round(608_000 / 4054.698259, 2))
    assert decision.provisional_credit_candidate is True
    assert decision.provisional_credit_amount_usd == 149.95


def test_pol_esc_500_above_500_escalates():
    """Amounts > $500 USD trigger mandatory HITL escalation (POL-ESC-500) with no card hold."""
    decision = evaluate(customer_segment="Premium", customer_country="México", account_age_days=400,
                        transaction_amount=850.0, amount_usd=850.0)
    assert decision.is_eligible
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert not decision.provisional_credit_candidate
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-ESC-500"]
    assert decision.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    assert decision.action_required == "ESCALATE"
    assert decision.card_lock_recommended is False


def test_pol_esc_500_exactly_500_continues():
    """The ceiling is strict: exactly $500 is still an autonomous intake, without a credit candidate flag."""
    decision = evaluate(transaction_amount=500.0, amount_usd=500.0)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert "POL-AUT-150" not in decision.cited_clauses


@pytest.mark.parametrize("amount, currency, rate, expected_outcome", [
    (178_000.0, "ARS", 355.912847, "MANDATORY_HITL_ESCALATION"),   # 500.13 USD
    (2_027_000.0, "COP", 4054.698259, "AUTONOMOUS_RESOLUTION"),    # 499.91 USD
])
def test_pol_esc_500_currency_matrix(amount, currency, rate, expected_outcome):
    """Caps are compared in USD at the dataset's 2026-06-17 rates; the customer text keeps the local amount."""
    decision = evaluate(transaction_amount=amount, transaction_currency=currency, amount_usd=round(amount / rate, 2))
    assert decision.policy_outcome == expected_outcome
    assert currency in decision.explanation_es


def test_pol_esc_legal_regulator_keyword_escalates():
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
        transaction_type="Purchase",
        transaction_status="Approved",
        amount_usd=50.0,
        customer_message="Si no me solucionan voy a poner la queja en CONDUSEF inmediatamente",
        current_date=date(2026, 6, 17)
    )
    decision = DisputePolicyEngine.evaluate(p_input)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.cited_clauses == ["POL-ESC-LEGAL"]
    assert decision.escalation_reason == "REGULATOR_OR_LEGAL_CITING"
    assert decision.action_required == "ESCALATE"


# ---------------------------------------------------------------- POL-ESC-LEGAL

def test_pol_esc_legal_pt_legal_keyword_escalates():
    """Portuguese legal wording escalates just like the Spanish regulator names."""
    decision = evaluate(customer_message="Se não resolverem vou falar com meu advogado")
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "REGULATOR_OR_LEGAL_CITING"
    assert decision.cited_clauses == ["POL-ESC-LEGAL"]


def test_pol_esc_legal_precedes_window():
    """POL-ESC-LEGAL runs before POL-WIN-60, so it escalates even an out-of-window charge."""
    decision = evaluate(transaction_date=date(2026, 3, 19), customer_message="Voy a quejarme ante la SFC")
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "REGULATOR_OR_LEGAL_CITING"
    assert "POL-WIN-60" not in decision.cited_clauses


def test_pol_esc_legal_escalates_without_card_hold():
    """A legal escalation transfers the case; it does not lock a card nobody reported stolen."""
    decision = evaluate(customer_message="voy a poner una demanda")
    assert decision.action_required == "ESCALATE"
    assert decision.card_lock_recommended is False


# ---------------------------------------------------- POL-CLARIFY / POL-ESC-AMBIG

NO_CHARGE = dict(transaction_id=None, transaction_date=None, transaction_amount=None,
                 transaction_currency=None, amount_usd=None, transaction_type=None, transaction_status=None)


def test_pol_clarify_zero_candidates_asks():
    """No candidate charge: ask, list nothing, open no case."""
    decision = evaluate(candidate_charges_count=0, **NO_CHARGE)
    assert decision.policy_outcome == "CLARIFICATION_REQUIRED"
    assert decision.action_required == "ASK_CLARIFICATION"
    assert decision.clarification_reason == "NO_CANDIDATE_CHARGE"
    assert decision.cited_clauses == ["POL-CLARIFY"]
    assert decision.case_values == {}


def test_pol_clarify_several_candidates_asks():
    """Two matching charges: ask which one, even when the caller passed one of them."""
    decision = evaluate(candidate_charges_count=2)
    assert decision.policy_outcome == "CLARIFICATION_REQUIRED"
    assert decision.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"


def test_pol_clarify_single_candidate_continues():
    decision = evaluate(candidate_charges_count=1)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.clarification_reason is None


@pytest.mark.parametrize("confidence, expected_outcome, expected_reason", [
    (0.69, "CLARIFICATION_REQUIRED", "LOW_INTENT_CONFIDENCE"),
    (0.70, "AUTONOMOUS_RESOLUTION", None),
])
def test_pol_clarify_intent_confidence_boundary(confidence, expected_outcome, expected_reason):
    """Jev intent confidence below 0.70 asks; exactly 0.70 continues."""
    decision = evaluate(dispute_intent="cargo_no_reconocido", intent_confidence=confidence)
    assert decision.policy_outcome == expected_outcome
    assert decision.clarification_reason == expected_reason


@pytest.mark.parametrize("stolen, asks", [(0.39, False), (0.40, True), (0.60, True), (0.61, False)])
def test_pol_clarify_stolen_card_band_boundaries(stolen, asks):
    """Jev stolen-card probability in the inclusive band [0.40, 0.60] asks whether the card is at hand."""
    decision = evaluate(is_stolen_reported=stolen)
    if asks:
        assert decision.policy_outcome == "CLARIFICATION_REQUIRED"
        assert decision.clarification_reason == "STOLEN_CARD_AMBIGUOUS"
    else:
        assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"


def test_pol_clarify_yields_to_legal():
    """Legal citation wins over a missing charge: POL-ESC-LEGAL runs first."""
    decision = evaluate(candidate_charges_count=0, customer_message="Voy a ir a la CONDUSEF", **NO_CHARGE)
    assert decision.cited_clauses == ["POL-ESC-LEGAL"]


@pytest.mark.parametrize("missing", ["transaction_id", "transaction_date", "transaction_amount", "transaction_currency",
                                     "transaction_type", "transaction_status"])
def test_pol_clarify_single_candidate_requires_charge(missing):
    """Past POL-CLARIFY with one candidate, a missing charge field is a programming error, not a decision."""
    with pytest.raises(ValueError):
        evaluate(candidate_charges_count=1, **{missing: None})


def test_pol_clarify_ambiguous_out_of_scope_asks():
    """Guardrail (P4): an out-of-scope reading without decisive confidence asks instead of abstaining."""
    decision = evaluate(dispute_intent="fuera_de_alcance", intent_confidence=0.65,
                        out_of_scope_category="prestamo_o_credito", candidate_charges_count=0, **NO_CHARGE)
    assert decision.policy_outcome == "CLARIFICATION_REQUIRED"
    assert decision.clarification_reason == "LOW_INTENT_CONFIDENCE"


@pytest.mark.parametrize("attempts, expected_outcome", [(1, "CLARIFICATION_REQUIRED"), (2, "MANDATORY_HITL_ESCALATION")])
def test_pol_esc_ambig_after_two_attempts(attempts, expected_outcome):
    """Still unresolved after two clarification questions: a human takes over (POL-ESC-AMBIG)."""
    decision = evaluate(candidate_charges_count=0, clarification_attempts=attempts, **NO_CHARGE)
    assert decision.policy_outcome == expected_outcome
    if attempts == 2:
        assert decision.escalation_reason == "UNRESOLVED_AFTER_CLARIFICATIONS"
        assert decision.cited_clauses == ["POL-CLARIFY", "POL-ESC-AMBIG"]
        assert decision.action_required == "ESCALATE"


# --------------------------------------------------------------- POL-DISP-TYPE

def test_pol_disp_type_transfer_is_disputable():
    """Decided 26-Sep: Transfer is disputable like Purchase, Payment and Withdrawal."""
    decision = evaluate(transaction_type="Transfer")
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"


@pytest.mark.parametrize("status", ["Declined", "Reversed", "Pending"])
def test_pol_disp_type_not_approved_abstains(status):
    decision = evaluate(transaction_status=status)
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert decision.escalation_reason == "NOT_DISPUTABLE_CHARGE"
    assert decision.action_required == "ABSTAIN"
    assert decision.cited_clauses == ["POL-DISP-TYPE"]
    assert decision.case_values == {}


@pytest.mark.parametrize("tx_type", ["Deposit", "Adjustment"])
def test_pol_disp_type_credit_types_abstain(tx_type):
    decision = evaluate(transaction_type=tx_type)
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert decision.escalation_reason == "NOT_DISPUTABLE_CHARGE"


def test_pol_disp_type_future_dated_charge_is_data_error():
    """06:00 UTC on 2026-06-18 opens process day 2026-06-18, one day after today: a data error, not a window case."""
    decision = evaluate(transaction_date=datetime(2026, 6, 18, 6, 0))
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert decision.escalation_reason == "DATA_ERROR_FUTURE_DATE"
    assert decision.data_quality_flag == "FUTURE_DATED_CHARGE"
    assert decision.cited_clauses == ["POL-DISP-TYPE"]
    assert "hace -1" not in decision.explanation_es


def test_pol_disp_type_out_of_scope_intent_abstains():
    """A decisive out-of-scope reading abstains and explains the scope (assumption S4)."""
    decision = evaluate(dispute_intent="fuera_de_alcance", intent_confidence=0.9,
                        out_of_scope_category="prestamo_o_credito", candidate_charges_count=0, **NO_CHARGE)
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert decision.escalation_reason == "OUT_OF_SCOPE_INTENT"
    assert decision.action_required == "ABSTAIN"
    assert decision.cited_clauses == ["POL-DISP-TYPE"]


def test_pol_disp_type_out_of_scope_names_category():
    """The abstention names the unsupported category in both languages; unknown categories are rejected."""
    decision = evaluate(dispute_intent="fuera_de_alcance", out_of_scope_category="prestamo_o_credito",
                        candidate_charges_count=0, **NO_CHARGE)
    assert "préstamos" in decision.explanation_es
    assert "empréstimos" in decision.explanation_pt
    assert set(DisputePolicyEngine.OUT_OF_SCOPE_LABELS) == set(OUT_OF_SCOPE_CATEGORIES)
    with pytest.raises(ValueError):
        evaluate(dispute_intent="fuera_de_alcance", out_of_scope_category="hipoteca", candidate_charges_count=0, **NO_CHARGE)


def test_pol_disp_type_missing_amount_usd_is_data_gap():
    """P2: a null USD amount past the cleaning step is a data defect a human must see, with the gap named."""
    decision = evaluate(transaction_amount=324599.21, transaction_currency="COP", amount_usd=None)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "DATA_GAP_AMOUNT_USD"
    assert decision.data_quality_flag == "MISSING_AMOUNT_USD"
    assert decision.cited_clauses == ["POL-DISP-TYPE"]
    assert decision.action_required == "ESCALATE"


def test_pol_disp_type_precedes_window():
    """A declined charge from 90 days ago is refused as not disputable, not as out of window."""
    decision = evaluate(transaction_status="Declined", transaction_date=date(2026, 3, 19))
    assert decision.escalation_reason == "NOT_DISPUTABLE_CHARGE"


# ------------------------------------------------------------------ POL-WIN-60

def test_pol_win_60_fixture_abstains():
    """The team fixture (synthetic-organizer): a real 77-day COP charge that would be a POL-AUT-150 candidate in window."""
    fixture = json.loads(Path("data/fixtures/abstention_pol_win_60.json").read_text())
    tx, cust, expected = fixture["transaction"], fixture["customer"], fixture["expected"]
    decision = evaluate(
        customer_id=tx["customer_id"], customer_segment=cust["segment"], customer_country=cust["country"],
        account_age_days=cust["account_age_days"], complaints_last_90d=cust["complaints_last_90d"],
        transaction_id=tx["transaction_id"], transaction_date=datetime.fromisoformat(tx["transaction_date_raw"]),
        transaction_amount=tx["amount"], transaction_currency=tx["currency"], amount_usd=tx["amount_usd"],
        transaction_type=tx["transaction_type"], transaction_status=tx["transaction_status"],
        current_date=date.fromisoformat(fixture["today"]),
    )
    assert decision.policy_outcome == expected["policy_outcome"]
    assert decision.action_required == expected["action_required"]
    assert decision.cited_clauses == expected["cited_clauses"] == ["POL-DISP-TYPE", "POL-WIN-60"]
    assert decision.is_eligible is False
    assert decision.provisional_credit_candidate is False
    assert decision.case_values == {}  # expected.case_opened is false
    assert f"hace {tx['days_since_local']} días" in decision.explanation_es


# ------------------------------------------------------------- POL-ESC-ML-RISK

@pytest.mark.parametrize("score, expected_outcome", [(0.70, "AUTONOMOUS_RESOLUTION"), (0.71, "MANDATORY_HITL_ESCALATION")])
def test_pol_esc_ml_risk_boundary(score, expected_outcome):
    """The learned risk threshold is strict: 0.70 continues, 0.71 escalates."""
    decision = evaluate(ml_risk_score=score)
    assert decision.policy_outcome == expected_outcome
    if score > 0.70:
        assert decision.escalation_reason == "HIGH_FRAUD_RISK_SCORE"
        assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-ESC-ML-RISK"]


def test_pol_esc_ml_risk_promises_no_lock():
    """High risk transfers the case to fraud prevention; it does not lock or promise to lock a card."""
    decision = evaluate(ml_risk_score=0.9)
    assert decision.action_required == "ESCALATE"
    assert decision.card_lock_recommended is False
    assert "bloqueo" not in decision.explanation_es.lower()
    assert "bloqueio" not in decision.explanation_pt.lower()


# --------------------------------------------------------------- POL-ESC-MULTI

def test_pol_esc_multi_two_charges_continue():
    decision = evaluate(recent_disputed_charges_count=2)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"


def test_pol_esc_multi_three_charges_escalate_with_lock():
    """More than two disputed charges in 48 h is multi-charge fraud: escalate and recommend the lock."""
    decision = evaluate(recent_disputed_charges_count=3)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "MULTIPLE_CHARGES_48H"
    assert decision.action_required == "ESCALATE"
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-ESC-MULTI"]
    assert decision.card_lock_recommended is True
    assert decision.card_lock_reason == "MULTI_CHARGE_FRAUD"


# ------------------------------------------------------------ POL-ESC-DISTRESS

@pytest.mark.parametrize("score, expected_outcome", [(1.99, "AUTONOMOUS_RESOLUTION"), (2.0, "MANDATORY_HITL_ESCALATION")])
def test_pol_esc_distress_score_boundary(score, expected_outcome):
    """Jev distress is an expected value; the brief's threshold is >= 2 with no rounding."""
    decision = evaluate(customer_distress_score=score)
    assert decision.policy_outcome == expected_outcome
    if score >= 2:
        assert decision.escalation_reason == "SEVERE_DISTRESS"
        assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-ESC-DISTRESS"]


@pytest.mark.parametrize("message", [
    "estoy desesperada, no tengo para comer",
    "estou desesperado, não tenho como pagar as contas",
])
def test_pol_esc_distress_keyword_fallback_es_pt(message):
    """Without a Jev score, the team's ES/PT keyword list escalates severe distress."""
    decision = evaluate(customer_message=message, customer_distress_score=None)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "SEVERE_DISTRESS"


def test_pol_esc_distress_jev_score_overrides_keywords():
    """With a Jev score present, the keyword list is not consulted (it is a fallback, S7)."""
    decision = evaluate(customer_message="estoy desesperada", customer_distress_score=0.5)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"


def test_pol_esc_distress_case_memory_escalates():
    """P3: a severe distress flag recorded in the case memory escalates even when today's score is low."""
    decision = evaluate(customer_distress_score=0.5, prior_distress_max_30d=2.5)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.escalation_reason == "SEVERE_DISTRESS"


# ---------------------------------------------------------- escalation order

def test_pol_esc_order_500_before_ml_risk():
    decision = evaluate(transaction_amount=850.0, amount_usd=850.0, ml_risk_score=0.9)
    assert decision.cited_clauses[-1] == "POL-ESC-500"
    assert decision.escalation_reason == "AMOUNT_EXCEEDS_500_USD"


def test_pol_esc_order_ml_risk_before_multi():
    decision = evaluate(ml_risk_score=0.9, recent_disputed_charges_count=3)
    assert decision.cited_clauses[-1] == "POL-ESC-ML-RISK"


def test_pol_esc_order_multi_before_distress():
    decision = evaluate(recent_disputed_charges_count=3, customer_distress_score=3.0)
    assert decision.cited_clauses[-1] == "POL-ESC-MULTI"


def test_pol_esc_order_secondary_clauses_recorded():
    """P1: the first clause decides; the other escalations that also fired are recorded for the handoff."""
    decision = evaluate(transaction_amount=850.0, amount_usd=850.0, ml_risk_score=0.9, recent_disputed_charges_count=3)
    assert decision.cited_clauses[-1] == "POL-ESC-500"
    assert decision.escalation_reason == "AMOUNT_EXCEEDS_500_USD"
    assert decision.secondary_clauses == ["POL-ESC-ML-RISK", "POL-ESC-MULTI"]
    assert decision.card_lock_recommended is True  # multi-charge fraud was claimed, whichever clause decided
    assert evaluate().secondary_clauses == []


# ---------------------------------------------------------------- POL-AUT-LOCK

@pytest.mark.parametrize("stolen, recommended", [(0.79, False), (0.80, True)])
def test_pol_aut_lock_stolen_probability_boundary(stolen, recommended):
    decision = evaluate(is_stolen_reported=stolen)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.card_lock_recommended is recommended
    assert decision.card_lock_reason == ("STOLEN_CARD_CLAIM" if recommended else None)


@pytest.mark.parametrize("message", ["me robaron la tarjeta ayer", "roubaram meu cartão ontem"])
def test_pol_aut_lock_keyword_fallback_es_pt(message):
    decision = evaluate(customer_message=message, is_stolen_reported=None)
    assert decision.card_lock_recommended is True
    assert decision.card_lock_reason == "STOLEN_CARD_CLAIM"


def test_pol_aut_lock_rides_along_autonomous_intake():
    """A stolen-card claim on an eligible small charge: open the case and recommend the lock."""
    decision = evaluate(is_stolen_reported=0.9, transaction_amount=80.0, amount_usd=80.0, complaints_last_90d=1)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.action_required == "OPEN_DISPUTE_ONLY"
    assert decision.card_lock_recommended is True


def test_pol_aut_lock_on_out_of_window_stolen_claim():
    """P5: the lock protects the customer even when the named charge is out of window."""
    decision = evaluate(is_stolen_reported=0.9, transaction_date=date(2026, 3, 19))
    assert decision.policy_outcome == "SAFE_POLICY_ABSTENTION"
    assert decision.card_lock_recommended is True
    assert decision.card_lock_reason == "STOLEN_CARD_CLAIM"


def test_pol_aut_lock_requires_customer_confirmation():
    """The lock is medium risk: session plus the customer's explicit yes (P5); no lock, no requirement."""
    assert evaluate(is_stolen_reported=0.9).card_lock_required_authentication == "SESSION_AND_CUSTOMER_CONFIRMATION"
    assert evaluate().card_lock_required_authentication is None


# -------------------------------------------------------------- POL-AUT-INTAKE

def test_pol_aut_intake_opens_case_with_dictionary_values():
    """The case is opened with data-dictionary values and the customer hears 'registered and under review'."""
    decision = evaluate(customer_segment="Basic", transaction_amount=300.0, amount_usd=300.0)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.action_required == "OPEN_DISPUTE_ONLY"
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE"]
    assert decision.case_values == {
        "case_type": "Claim", "category": "Transactions", "subcategory": "Cargo no reconocido",
        "reception_channel": "App", "status": "Open",
    }
    assert "INTAKE_RECEIVED" not in decision.explanation_es
    assert "INTAKE_RECEIVED" not in decision.explanation_pt
    assert "registrada" in decision.explanation_es
    assert "registrada" in decision.explanation_pt


def test_pol_aut_intake_subcategory_follows_intent():
    assert evaluate(dispute_intent="cobro_indebido", customer_segment="Basic").case_values["subcategory"] == "Cobro indebido"
    assert evaluate(dispute_intent="cargo_no_reconocido", customer_segment="Basic").case_values["subcategory"] == "Cargo no reconocido"


@pytest.mark.parametrize("amount", [150.01, 500.0])
def test_pol_aut_intake_above_150_is_not_candidate(amount):
    """Between $150 and $500 the case opens autonomously without a credit candidate flag."""
    decision = evaluate(transaction_amount=amount, amount_usd=amount)
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"
    assert decision.cited_clauses == ["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE"]
    assert decision.provisional_credit_amount_usd == 0.0


# ------------------------------------------- authentication matrix, passthroughs

def test_policy_action_auth_matrix_unlock_is_high():
    """P5: every supported action has a risk tier and an authentication level, declared as policy-as-code."""
    matrix = DisputePolicyEngine.ACTION_AUTH_MATRIX
    assert matrix["OPEN_DISPUTE_ONLY"] == ("LOW", "SESSION")
    assert matrix["ESCALATE"] == ("LOW", "SESSION")
    assert matrix["LOCK_CARD"] == ("MEDIUM", "SESSION_AND_CUSTOMER_CONFIRMATION")
    assert matrix["UNLOCK_CARD"] == ("HIGH", "STEP_UP_AND_AGENT")
    assert matrix["APPROVE_CREDIT_CANDIDATE"] == ("HIGH", "AGENT_ROLE")


def test_policy_required_authentication_by_action():
    matrix = DisputePolicyEngine.ACTION_AUTH_MATRIX
    assert evaluate().required_authentication == "SESSION"
    assert evaluate(amount_usd=850.0, transaction_amount=850.0).required_authentication == "SESSION"
    assert evaluate(candidate_charges_count=0, **NO_CHARGE).required_authentication == "SESSION"
    assert evaluate(transaction_status="Declined").required_authentication == "SESSION"
    assert evaluate(is_stolen_reported=0.9).card_lock_required_authentication == "SESSION_AND_CUSTOMER_CONFIRMATION"
    assert matrix["LOCK_CARD"][1] == "SESSION_AND_CUSTOMER_CONFIRMATION"


def test_policy_risk_and_memory_passthrough():
    """P1 and P3: the SHAP summary and the case memory ride through the decision untouched, for the handoff."""
    features = [{"feature": "is_foreign_country", "value": True, "contribution": 0.21}]
    decision = evaluate(risk_top_features=features, prior_distress_max_30d=0.5, prior_escalations_180d=2,
                        prior_cases_180d=3, prior_lock_refused=True)
    assert decision.risk_top_features == features
    assert decision.case_memory == {"prior_distress_max_30d": 0.5, "prior_escalations_180d": 2,
                                    "prior_cases_180d": 3, "prior_lock_refused": True}
    assert decision.policy_outcome == "AUTONOMOUS_RESOLUTION"


@pytest.mark.parametrize("overrides, expected_reason", [
    (dict(customer_message="voy a la CONDUSEF"), "REGULATOR_OR_LEGAL_CITING"),
    (dict(transaction_date=date(2026, 3, 19)), "OUT_OF_POLICY_WINDOW"),
])
def test_pol_aut_lock_multi_charge_on_any_outcome(overrides, expected_reason):
    """Audit finding 1: three charges in 48 h recommend the lock even when legal or the window decides."""
    decision = evaluate(recent_disputed_charges_count=3, **overrides)
    assert decision.escalation_reason == expected_reason
    assert decision.card_lock_recommended is True
    assert decision.card_lock_reason == "MULTI_CHARGE_FRAUD"


def test_pol_aut_lock_stolen_claim_names_the_reason_over_multi_charge():
    """When both apply, the more specific reason (stolen card) names the lock."""
    decision = evaluate(recent_disputed_charges_count=3, is_stolen_reported=0.9)
    assert decision.card_lock_reason == "STOLEN_CARD_CLAIM"


@pytest.mark.parametrize("decision_overrides", [dict(candidate_charges_count=0, clarification_attempts=2, **NO_CHARGE),
                                                dict(transaction_currency="COP", transaction_amount=1.0, amount_usd=None)])
def test_policy_escalation_without_eligible_charge_is_not_eligible(decision_overrides):
    """S12: escalations that happen before a charge passed the gates report is_eligible False."""
    decision = evaluate(**decision_overrides)
    assert decision.policy_outcome == "MANDATORY_HITL_ESCALATION"
    assert decision.is_eligible is False


def test_pol_esc_ml_risk_threshold_comes_from_the_input():
    """The transferred model's threshold is a percentile of the bank window (spec section 6), so the clause reads it from the input; 0.70 stays the default."""
    assert evaluate(ml_risk_score=0.10).policy_outcome == "AUTONOMOUS_RESOLUTION"
    decision = evaluate(ml_risk_score=0.10, ml_risk_threshold=0.0669)
    assert decision.escalation_reason == "HIGH_FRAUD_RISK_SCORE" and "POL-ESC-ML-RISK" in decision.cited_clauses
