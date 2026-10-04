"""The risk zone validator beside the learned risk score: where the charge was made, read with no model (TQ-038)."""
import json
import math

import pytest

from src.eval.fixture_bank import build_bank_fixture
from src.ml.bank_adapter import address_bucket
from src.ops.store import OpsStore
from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.rules.dispute_policy import OUTCOME_AUTONOMOUS
from src.tools.gateway import BankingToolGateway
from src.tools.risk_zone import ZONE_BUCKET, RiskZoneValidator, cross_check
from tests.conftest import make_session

HOME = {"country": "Colombia", "city": "Bogotá"}

PLACES = [
    # charge country, charge city, home country, home city, zone, in a risk zone
    ("Colombia", "Bogotá", "Colombia", "Bogotá", "HOME", False),
    ("Colombia", None, "Colombia", "Bogotá", "HOME", False),  # no city on the charge: the country decides
    ("Colombia", float("nan"), "Colombia", "Bogotá", "HOME", False),  # a NULL as pandas reads it, in a measurement over the lakehouse
    ("Colombia", "Medellín", "Colombia", "Bogotá", "DOMESTIC_OTHER_CITY", False),
    ("Spain", "Madrid", "Colombia", "Bogotá", "ABROAD", True),
    ("Mexico", "Puebla", "México", "Puebla", "HOME", False),  # the dataset spells the country both ways
    ("Mexico", "Puebla", "Colombia", "Bogotá", "ABROAD", True),
    (None, None, "Colombia", "Bogotá", "UNKNOWN", False),
    ("Colombia", "Bogotá", None, None, "UNKNOWN", False),
]


def _row(transaction_id, when, country, city):
    return {"transaction_id": transaction_id, "transaction_date": when, "transaction_country": country, "transaction_city": city}


# ------------------------------------------------------------------ the verdict
@pytest.mark.parametrize("tx_country, tx_city, home_country, home_city, zone, risky", PLACES)
def test_the_zone_is_where_the_charge_was_made_relative_to_the_customers_home(tx_country, tx_city, home_country, home_city, zone, risky):
    verdict = RiskZoneValidator()(_row("T-1", "2026-06-10T12:00:00", tx_country, tx_city), [], {"country": home_country, "city": home_city})
    assert (verdict.zone, verdict.in_risk_zone) == (zone, risky)


@pytest.mark.parametrize("tx_country, tx_city, home_country, home_city, zone, risky", PLACES)
def test_the_zone_agrees_with_the_address_bucket_the_model_reads(tx_country, tx_city, home_country, home_city, zone, risky):
    """Two code paths, one geography: the validator shares no code with the feature the scorer computes."""
    bucket = address_bucket(tx_country, tx_city, home_country, home_city)
    verdict = RiskZoneValidator()(_row("T-1", "2026-06-10T12:00:00", tx_country, tx_city), [], {"country": home_country, "city": home_city})
    assert ZONE_BUCKET.get(verdict.zone) == (None if math.isnan(bucket) else bucket)


def test_a_city_the_gateway_escaped_compares_as_the_profile_spells_it():
    verdict = RiskZoneValidator()(_row("T-1", "2026-06-10T12:00:00", "Spain", "L&#x27;Hospitalet"), [], {"country": "Spain", "city": "L'Hospitalet"})
    assert verdict.zone == "HOME"


def test_the_customers_earlier_charges_in_the_same_country_are_counted():
    charge = _row("T-4", "2026-06-10T12:00:00", "Spain", "Madrid")
    history = [_row("T-1", "2026-06-01T12:00:00", "Colombia", "Bogotá"), _row("T-2", "2026-06-05T12:00:00", "Spain", "Sevilla"),
               _row("T-3", "2026-06-08T12:00:00", "Spain", "Madrid"), charge, _row("T-5", "2026-06-12T12:00:00", "Spain", "Madrid")]
    verdict = RiskZoneValidator()(charge, history, HOME)
    assert (verdict.earlier_charges_read, verdict.earlier_charges_in_place) == (3, 2)  # T-5 came later; the charge is no history of itself


def test_the_fact_for_the_human_agent_names_the_places_and_the_verdict():
    validator = RiskZoneValidator()
    abroad = validator(_row("T-2", "2026-06-10T12:00:00", "Spain", "Madrid"), [_row("T-1", "2026-06-01T12:00:00", "Colombia", "Bogotá")], HOME)
    assert abroad.fact() == ("Risk zone check: charge made in Madrid, Spain, outside the customer's home country (Colombia): in a risk zone; "
                             "0 of the customer's 1 earlier charges read were made in Spain")
    assert validator(_row("T-1", "2026-06-10T12:00:00", "Colombia", "Bogotá"), [], HOME).fact() == (
        "Risk zone check: charge made in Bogotá, Colombia, the customer's home city: not in a risk zone")
    assert validator(_row("T-1", "2026-06-10T12:00:00", None, None), [], HOME).fact() == (
        "Risk zone check: not validated, the charge or the customer profile has no country on record")


@pytest.mark.parametrize("in_risk_zone, model_flags, expected", [
    (True, True, "BOTH"), (False, True, "MODEL_ONLY"), (True, False, "ZONE_ONLY"), (False, False, "NEITHER")])
def test_the_cross_check_names_which_check_flags_the_charge(in_risk_zone, model_flags, expected):
    assert cross_check(in_risk_zone, model_flags) == expected


# ------------------------------------------------------------ in the dispute turn
MADRID_850 = {"transaction_id": "TRX-Z-850", "customer_id": "CLI-Z-1", "product_id": "PRD-Z-1", "process_date": "2026-06-10", "amount": 850.0,
              "channel": "POS", "transaction_country": "Spain", "transaction_city": "Madrid", "merchant_name": "Tienda"}


class _Scorer:
    """A scorer that, like the transferred one, scores Web and App only and says so with None."""
    channels = ("Web", "App")
    policy_threshold = 0.5

    def __init__(self, score):
        self.score = score

    def __call__(self, matched, history, profile):
        return (None, []) if matched.get("channel") not in self.channels else (self.score, [])


def _stack(path, transactions, scorer=None, validator=None):
    bank = build_bank_fixture(
        path, [{"customer_id": "CLI-Z-1", "segment": "Plus", "country": "Colombia", "city": "Bogotá", "account_age_days": 400}],
        [{"product_id": "PRD-Z-1", "customer_id": "CLI-Z-1", "currency": "COP"}], transactions)
    ops = OpsStore(":memory:")
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank), ops=ops, risk_scorer=scorer, zone_validator=validator)
    session = make_session("CLI-Z-1")
    return orchestrator, ops, session, orchestrator.start_conversation(session)["conversation_id"]


def _zone_rows(ops, cid):
    return [a["details"] for a in ops.list_audit(conversation_id=cid) if a["action"] == "RISK_ZONE_VALIDATED"]


def test_the_handoff_and_the_audit_log_carry_the_verdict_and_the_customer_never_sees_it(tmp_path):
    orchestrator, ops, session, cid = _stack(tmp_path / "bank.duckdb", [MADRID_850], validator=RiskZoneValidator())
    turn = orchestrator.handle_message(session, cid, "No reconozco un cargo de 850 dólares en Tienda")
    facts = ops.get_handoff(turn.handoff_id)["packet"]["verified_facts"]
    assert ("Risk zone check: charge made in Madrid, Spain, outside the customer's home country (Colombia): in a risk zone; "
            "no earlier charge of the customer was read") in facts
    [details] = _zone_rows(ops, cid)
    assert (details["transaction_id"], details["zone"], details["in_risk_zone"]) == ("TRX-Z-850", "ABROAD", True)
    assert (details["ml_scored"], details["cross_check"]) == (False, "ZONE_ONLY")  # no model is loaded: the zone check stands alone
    shown = json.dumps(turn.as_dict(), ensure_ascii=False)
    assert "Madrid" not in shown and "ABROAD" not in shown and "risk zone" not in shown.lower()


def test_a_charge_in_a_risk_zone_keeps_the_outcome_the_policy_gives_without_the_validator(tmp_path):
    charge = {**MADRID_850, "transaction_id": "TRX-Z-080", "amount": 80.0}
    outcomes = []
    for name, validator in (("without.duckdb", None), ("with.duckdb", RiskZoneValidator())):
        orchestrator, ops, session, cid = _stack(tmp_path / name, [charge], validator=validator)
        turn = orchestrator.handle_message(session, cid, "No reconozco un cargo de 80 dólares en Tienda")
        outcomes.append((turn.policy_outcome, turn.cited_clauses, turn.state, turn.reply.split(" Número de caso")[0], len(_zone_rows(ops, cid))))
    assert outcomes[0][:4] == outcomes[1][:4] and outcomes[1][0] == OUTCOME_AUTONOMOUS
    assert (outcomes[0][4], outcomes[1][4]) == (0, 1)  # the verdict is recorded, and nothing else moves


@pytest.mark.parametrize("channel, score, country, city, ml_scored, expected", [
    ("Web", 0.9, "Spain", "Madrid", True, "BOTH"),
    ("Web", 0.9, "Colombia", "Bogotá", True, "MODEL_ONLY"),
    ("Web", 0.2, "Spain", "Madrid", True, "ZONE_ONLY"),
    ("POS", 0.9, "Spain", "Madrid", False, "ZONE_ONLY"),  # a channel the model does not score: only the zone check reads the charge
    ("Web", 0.2, "Colombia", "Bogotá", True, "NEITHER"),
])
def test_the_audit_row_cross_checks_the_zone_against_the_model(tmp_path, channel, score, country, city, ml_scored, expected):
    charge = {**MADRID_850, "transaction_id": "TRX-Z-080", "amount": 80.0, "channel": channel, "transaction_country": country, "transaction_city": city}
    orchestrator, ops, session, cid = _stack(tmp_path / "bank.duckdb", [charge], scorer=_Scorer(score), validator=RiskZoneValidator())
    orchestrator.handle_message(session, cid, "No reconozco un cargo de 80 dólares en Tienda")
    [details] = _zone_rows(ops, cid)
    assert (details["ml_scored"], details["ml_above_threshold"], details["cross_check"]) == (ml_scored, ml_scored and score > 0.5, expected)


def test_a_turn_that_identifies_no_charge_validates_nothing(tmp_path):
    other = {**MADRID_850, "transaction_id": "TRX-Z-851", "merchant_name": "Mercado"}
    orchestrator, ops, session, cid = _stack(tmp_path / "bank.duckdb", [MADRID_850, other], validator=RiskZoneValidator())
    turn = orchestrator.handle_message(session, cid, "No reconozco un cargo de 850 dólares")
    assert turn.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES" and _zone_rows(ops, cid) == []


# ------------------------------------------------------------------ in the API
def test_the_api_orchestrator_runs_the_zone_validator(tmp_path, monkeypatch):
    from src.api.dispute_routes import get_orchestrator

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("LAKEHOUSE_PATH", build_bank_fixture(tmp_path / "bank.duckdb", [], [], []))
    monkeypatch.setenv("OPS_DB_PATH", str(tmp_path / "ops.duckdb"))
    monkeypatch.setenv("FRAUD_MODEL_PATH", str(tmp_path / "no-model.joblib"))
    monkeypatch.setenv("RAG_GATE_PATH", str(tmp_path / "no-gate.json"))
    get_orchestrator.cache_clear()
    try:
        assert isinstance(get_orchestrator().zone_validator, RiskZoneValidator)
    finally:
        get_orchestrator.cache_clear()
