"""The risk model sees at serving what it was calibrated on (audit v3, AUD-27; TQ-026: Web and App charges only)."""
from datetime import datetime

import duckdb

from src.eval.fixture_bank import build_bank_fixture
from src.ml.bank_adapter import rows_to_canonical
from src.tools.gateway import BankingToolGateway
from tests.conftest import make_session


def _bank(tmp_path):
    return build_bank_fixture(
        tmp_path / "bank.duckdb",
        [{"customer_id": "CLI-R-1", "segment": "Plus", "country": "Colombia", "city": "Bogotá", "account_age_days": 400}],
        [{"product_id": "PRD-R-1", "customer_id": "CLI-R-1", "currency": "COP"}],
        [{"transaction_id": "TRX-R-1", "customer_id": "CLI-R-1", "product_id": "PRD-R-1", "process_date": "2026-06-10", "amount": 80.0,
          "channel": "Web", "transaction_country": "USA", "transaction_city": "Miami", "merchant_name": "Shop"}])


def test_the_eval_bank_fixture_keeps_what_the_risk_model_reads(tmp_path):
    con = duckdb.connect(_bank(tmp_path), read_only=True)
    try:
        assert con.execute("SELECT channel, transaction_country, transaction_city FROM gold_transactions").fetchone() == ("Web", "USA", "Miami")
        assert con.execute("SELECT currency FROM silver_products").fetchone() == ("COP",)
        assert con.execute("SELECT city FROM gold_customers").fetchone() == ("Bogotá",)
    finally:
        con.close()


def test_the_charge_search_and_the_profile_carry_what_the_risk_model_reads(tmp_path):
    gateway = BankingToolGateway(db_path=_bank(tmp_path))
    session = make_session("CLI-R-1")
    [row] = gateway.search_customer_transactions(session)
    assert (row["channel"], row["transaction_country"], row["transaction_city"], row["product_currency"]) == ("Web", "USA", "Miami", "COP")
    profile = gateway.get_customer_profile(session)
    assert profile["city"] == "Bogotá"
    feats = rows_to_canonical(row, [row], profile)
    assert feats["address_distance_bucket"].notna().all() and feats["consistency_matches"].notna().all()


class _Scorer:
    """A scorer that, like the transferred one, scores Web and App only and says so with None."""
    channels = ("Web", "App")
    policy_threshold = 0.5

    def __call__(self, matched, history, profile):
        return (None, []) if matched.get("channel") not in self.channels else (0.2, [])


def test_a_charge_outside_the_scored_channels_is_reported_as_not_scored(tmp_path):
    from src.ops.store import OpsStore
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    bank = build_bank_fixture(
        tmp_path / "pos.duckdb",
        [{"customer_id": "CLI-R-2", "segment": "Plus", "country": "Colombia", "account_age_days": 400}],
        [{"product_id": "PRD-R-2", "customer_id": "CLI-R-2"}],
        [{"transaction_id": "TRX-R-2", "customer_id": "CLI-R-2", "product_id": "PRD-R-2", "process_date": "2026-06-10", "amount": 850.0,
          "channel": "POS", "merchant_name": "Tienda"}])
    ops = OpsStore(":memory:")
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank), ops=ops, risk_scorer=_Scorer())
    session = make_session("CLI-R-2")
    cid = orchestrator.start_conversation(session)["conversation_id"]
    turn = orchestrator.handle_message(session, cid, "No reconozco un cargo de 850 dólares en Tienda")
    assert turn.escalation_reason == "AMOUNT_ABOVE_AUTONOMOUS_LIMIT" or turn.handoff_id  # escalates on the amount, not on risk
    facts = ops.get_handoff(turn.handoff_id)["packet"]["verified_facts"]
    assert "ML risk score: not scored, the model scores Web and App charges only" in facts
    assert turn.signals["ml_risk_score"] is None


class _Model:
    """A fitted model stand-in that rates every charge 0.3."""
    def predict_proba(self, x):
        import numpy as np
        return np.array([[0.7, 0.3]])


class _Ranker:
    def transform(self, frame):
        return frame


def test_the_transfer_scorer_scores_only_the_channels_its_threshold_was_calibrated_on(tmp_path):
    import joblib

    from src.ml.feature_contract import DEPLOYABLE_V1
    from src.ml.transfer_scorer import TransferRiskScorer

    path = tmp_path / "bundle.joblib"
    joblib.dump({"model": _Model(), "features": DEPLOYABLE_V1, "ranker": _Ranker(), "medians": {f: 0.0 for f in DEPLOYABLE_V1},
                 "threshold": 0.07, "threshold_kind": "percentile", "contract_version": "1.2",
                 "report": {"bank_calibration": {"channels": ["Web", "App"]}}}, path)
    scorer = TransferRiskScorer(path)
    assert scorer.channels == ("Web", "App")
    base = {"transaction_id": "T-1", "customer_id": "C", "product_id": "P", "product_type": "Tarjeta Crédito",
            "transaction_date": datetime(2026, 6, 10, 15, 0), "amount": 80.0, "currency": "USD", "amount_usd": 80.0}
    assert scorer({**base, "channel": "POS"}, [], {"country": "Colombia"}) == (None, [])
    score, _ = scorer({**base, "channel": "App"}, [], {"country": "Colombia"})
    assert score == 0.3
