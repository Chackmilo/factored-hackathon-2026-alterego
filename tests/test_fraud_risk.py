"""Risk model pipeline on a synthetic bank: features, time split, cost threshold, report, and the scorer hook in the orchestrator."""
import random
from datetime import datetime, timedelta

import duckdb
import numpy as np
import pandas as pd
import pytest

from src.eval.fixture_bank import BANK_SCHEMAS
from src.ml.fraud_risk import (
    FEATURES,
    RiskScorer,
    build_features,
    cost_threshold,
    rules_baseline_score,
    train,
)


@pytest.fixture
def synthetic_bank(tmp_path):
    """300 charges of 20 customers over 20 days; fraud is foreign Web charges of large amounts at night."""
    rng = random.Random(3)
    path = tmp_path / "synthetic_bank.duckdb"
    con = duckdb.connect(str(path))
    for ddl in BANK_SCHEMAS.values():
        con.execute(ddl)
    for i in range(20):
        con.execute("INSERT INTO gold_customers (customer_id, full_name, country, segment, account_age_days, is_account_mature, complaints_last_90d, active_products) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [f"CLI-{i:03d}", f"Cliente {i}", rng.choice(["Colombia", "México", "Argentina"]), "Plus", rng.randint(30, 900), True, 0, 1])
    rows = []
    for n in range(300):
        cust = f"CLI-{rng.randint(0, 19):03d}"
        day = datetime(2026, 5, 28) + timedelta(days=rng.randint(0, 19), hours=rng.randint(6, 29), minutes=rng.randint(0, 59))
        fraud = rng.random() < 0.06
        amount = rng.uniform(900, 3000) if fraud else rng.uniform(5, 400)
        channel = "Web" if fraud else rng.choice(["POS", "ATM", "App", "POS"])
        country = "USA" if fraud else rng.choice(["Colombia", "México", "Argentina"])
        rows.append((f"TRX-{n:04d}", day, (day - timedelta(hours=6)).date(), cust, f"PRD-{cust[4:]}", "Purchase", amount, "USD", amount, "same_currency",
                     channel, rng.choice(["Food", "Services", None]), country, "Approved", fraud, 0.0))
    con.executemany("""INSERT INTO gold_transactions (transaction_id, transaction_date, process_date, customer_id, product_id, transaction_type,
        amount, currency, amount_usd, amount_usd_source, channel, merchant_category, transaction_country, transaction_status, is_fraud, fraud_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
    con.close()
    return path


def test_features_are_leak_free_and_velocity_uses_earlier_rows_only():
    tx = pd.DataFrame([
        {"transaction_id": "A", "customer_id": "C1", "transaction_date": "2026-06-10 10:00:00", "amount_usd": 100.0, "channel": "POS", "merchant_category": "Food", "transaction_country": "Mexico", "transaction_type": "Purchase"},
        {"transaction_id": "B", "customer_id": "C1", "transaction_date": "2026-06-10 12:00:00", "amount_usd": 300.0, "channel": "Web", "merchant_category": None, "transaction_country": "USA"},
    ])
    customers = pd.DataFrame([{"customer_id": "C1", "country": "México", "account_age_days": 500, "segment": "Plus"}])
    f = build_features(tx, customers).set_index("transaction_id")
    assert "fraud_score" not in FEATURES and "is_fraud" not in FEATURES
    assert {"account_age_days", "country_México", "segment_Plus"} <= set(FEATURES)  # tenure, country and segment are inputs
    assert f.loc["A", "country_México"] == 1.0 and f.loc["A", "segment_Plus"] == 1.0 and f.loc["A", "segment_Basic"] == 0.0
    assert f.loc["A", "type_Purchase"] == 1.0 and f.loc["B", "type_Purchase"] == 0.0  # transaction type is an input too
    assert f.loc["A", "is_foreign_country"] == 0.0 and f.loc["B", "is_foreign_country"] == 1.0  # Mexico normalized to México
    assert f.loc["A", "velocity_24h_count"] == 0 and f.loc["B", "velocity_24h_count"] == 1 and f.loc["B", "velocity_24h_sum"] == 100.0
    assert f.loc["B", "ratio_to_historical_avg"] == 3.0 and f.loc["B", "card_not_present"] == 1.0
    assert rules_baseline_score(f).tolist() == [0.0, 0.5]  # card not present and foreign; the ratio rule is strict (3.0 does not fire)


def test_cost_threshold_penalizes_missed_fraud_ten_times():
    y = np.array([0, 0, 0, 0, 1, 1])
    scores = np.array([0.1, 0.2, 0.3, 0.6, 0.55, 0.9])
    threshold, cost = cost_threshold(y, scores)
    assert threshold <= 0.55 and cost == 1.0  # one unnecessary verification beats one missed fraud (cost 10)


def test_training_writes_report_and_model_beats_rules_on_the_held_out_days(synthetic_bank, tmp_path):
    report = train(synthetic_bank, tmp_path / "ml", tmp_path / "fraud_risk.joblib")
    assert report["fraud_score_used"] is False and report["split"]["test_positives"] > 0
    assert (tmp_path / "ml" / "fraud_risk.md").exists() and (tmp_path / "ml" / "fraud_risk.json").exists()
    model_test, rules_test = report["model"]["test"], report["rules_baseline"]["test"]
    assert model_test["roc_auc"] is not None and model_test["roc_auc"] >= rules_test["roc_auc"] - 0.05
    assert model_test["missed_fraud"] <= rules_test["missed_fraud"]


def test_scorer_hook_feeds_the_policy(synthetic_bank, tmp_path, bank_fixture_db, ops_store, owner_session):
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway
    train(synthetic_bank, tmp_path / "ml", tmp_path / "fraud_risk.joblib")
    scorer = RiskScorer(tmp_path / "fraud_risk.joblib")
    charge = {"transaction_id": "TRX-X", "transaction_date": "2026-06-16 09:00:00", "amount_usd": 2500.0, "channel": "Web",
              "merchant_category": None, "transaction_country": "USA", "transaction_type": "Withdrawal"}
    score, top = scorer(charge, [], {"country": "Colombia", "account_age_days": 40, "segment": "Basic"})
    assert 0.0 <= score <= 1.0 and len(top) == 3 and all({"feature", "phrase", "value", "contribution"} <= set(t) for t in top)
    row = scorer._row(charge, {"country": "Colombia"})
    assert row["transaction_type"] == "Withdrawal" and row["amount_usd"] == 2500.0  # the served features match the training ones
    # a scorer that flags the charge makes POL-ESC-ML-RISK decide, with the features passed through to the handoff
    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store,
                                       risk_scorer=lambda matched, history, profile: (0.91, [{"feature": "is_foreign_country", "phrase": "Charge made outside the customer's country", "value": 1.0, "contribution": 0.3}]))
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert turn.escalation_reason == "HIGH_FRAUD_RISK_SCORE"
    packet = ops_store.get_handoff(turn.handoff_id)["packet"]
    assert packet["risk_explanation"]["score"] == 0.91 and packet["risk_explanation"]["top_features"][0]["feature"] == "is_foreign_country"
