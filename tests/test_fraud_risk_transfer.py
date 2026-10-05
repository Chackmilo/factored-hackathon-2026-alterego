"""Transfer trainer: competition time split, ablations, percentile threshold on the bank window, scorer ordering, leakage guards."""
import random
from datetime import datetime, timedelta

import duckdb
import pandas as pd
import pytest

from src.eval.fixture_bank import BANK_SCHEMAS
from src.ml.feature_contract import CONTRACT_V1, DEPLOYABLE_V1
from src.ml.fraud_risk_transfer import train
from src.ml.transfer_scorer import TransferRiskScorer


@pytest.fixture
def competition_dir(tmp_path):
    """3,000 competition-shaped rows over 60 days; fraud is a new card (D1 small) paying a large amount soon after its previous charge."""
    rng = random.Random(11)
    rows = []
    for i in range(3000):
        day = rng.randint(0, 59)
        card = rng.randint(1, 400)
        d1 = rng.choice([0, 1, 3, 30, 120, 400])
        fraud = rng.random() < (0.35 if d1 <= 3 else 0.01)
        amt = rng.uniform(300, 900) if fraud else rng.uniform(10, 200)
        rows.append({"TransactionID": i, "isFraud": int(fraud), "TransactionDT": day * 86400 + rng.randint(0, 86399), "TransactionAmt": round(amt, 2),
                     "ProductCD": "W", "card1": card, "card6": rng.choice(["credit", "debit"]), "addr1": rng.choice([100.0, 200.0]), "dist1": rng.choice([0.0, 5.0, 200.0, None]),
                     "D1": d1, "M1": rng.choice(["T", "F", None]), "M2": "T", "M3": "T", "M4": "M0", "M5": None, "M6": "F", "M7": None, "M8": None, "M9": None})
    pd.DataFrame(rows).to_csv(tmp_path / "train_transaction.csv", index=False)
    return tmp_path


@pytest.fixture
def bank_db(tmp_path):
    """A small lakehouse: 40 Web and App charges of 4 customers in the serving window, plus two POS ones that must stay out."""
    path = tmp_path / "bank.duckdb"
    con = duckdb.connect(str(path))
    for ddl in BANK_SCHEMAS.values():
        con.execute(ddl)
    for i in range(4):
        con.execute("INSERT INTO gold_customers (customer_id, full_name, country, city, segment, account_age_days, is_account_mature, complaints_last_90d, active_products) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [f"CLI-{i}", f"C {i}", "Colombia", "Bogotá", "Plus", 500, True, 0, 1])
        con.execute("INSERT INTO silver_products (product_id, customer_id, product_type, currency, opening_date, product_status) VALUES (?, ?, ?, ?, ?, ?)",
                    [f"PRD-{i}", f"CLI-{i}", "Tarjeta Crédito", "COP", "2024-01-01", "Active"])
    rng = random.Random(5)
    for n in range(42):
        cust = n % 4
        day = datetime(2026, 5, 1) + timedelta(days=rng.randint(0, 45), hours=rng.randint(6, 29))
        channel = "POS" if n >= 40 else rng.choice(["Web", "App"])
        con.execute("""INSERT INTO silver_transactions (transaction_id, transaction_date, process_date, product_id, customer_id, transaction_type, amount, currency, amount_usd,
                       channel, transaction_country, transaction_city, transaction_status, is_fraud) VALUES (?, ?, ?, ?, ?, 'Purchase', ?, 'COP', ?, ?, 'Colombia', 'Bogotá', 'Approved', ?)""",
                    [f"TRX-{n}", day, (day - timedelta(hours=6)).date(), f"PRD-{cust}", f"CLI-{cust}", 400000.0, rng.uniform(20, 900), channel, n == 7])
    con.close()
    return path


def test_train_reports_competition_split_ablations_and_bank_percentile(competition_dir, bank_db, tmp_path):
    report = train(competition_dir, tmp_path / "reports", tmp_path / "model.joblib", lakehouse=bank_db, holdout_fraction_of_days=0.25, percentile=90.0)
    assert report["fraud_score_used"] is False and report["contract_version"] == "1.1" and report["features"] == DEPLOYABLE_V1
    assert report["split"]["test_rows"] > 0 and report["split"]["test_positives"] > 0
    assert report["model"]["test"]["roc_auc"] > 0.75  # the planted signal is learnable through the contract
    assert set(report["ablations"]) == {"without_card_aggregates", "without_discrete_block"}
    assert all("roc_auc" in a["test"] for a in report["ablations"].values())
    bank = report["bank_calibration"]
    assert bank["charges_scored"] == 40 and bank["channels"] == ["Web", "App"] and bank["percentile"] == 90.0
    assert report["threshold_kind"] == "percentile" and 0.0 < report["threshold"] <= 1.0
    assert bank["share_above_threshold"] == pytest.approx(0.10, abs=0.06)
    assert (tmp_path / "reports" / "fraud_risk_transfer.json").exists() and (tmp_path / "reports" / "fraud_risk_transfer.md").exists()


def test_train_without_lakehouse_falls_back_to_the_competition_percentile(competition_dir, tmp_path):
    report = train(competition_dir, tmp_path / "reports", tmp_path / "model.joblib", holdout_fraction_of_days=0.25)
    assert report["bank_calibration"] is None and report["threshold_kind"] == "percentile_competition_holdout"


def test_scorer_keeps_the_orchestrator_signature_and_orders_a_bursty_new_card_charge_first(competition_dir, bank_db, tmp_path):
    train(competition_dir, tmp_path / "reports", tmp_path / "model.joblib", lakehouse=bank_db, holdout_fraction_of_days=0.25)
    scorer = TransferRiskScorer(tmp_path / "model.joblib")
    profile = {"country": "Colombia", "city": "Bogotá", "segment": "Plus", "account_age_days": 20}
    history = [{"transaction_id": f"H{i}", "customer_id": "CLI-9", "product_id": "PRD-9", "product_type": "Tarjeta Crédito", "channel": "App",
                "transaction_date": datetime(2026, 6, 10, 12, 0) + timedelta(hours=i), "amount": 30.0, "currency": "USD", "amount_usd": 30.0} for i in range(3)]
    risky = {"transaction_id": "T-RISKY", "customer_id": "CLI-9", "product_id": "PRD-9", "product_type": "Tarjeta Crédito", "channel": "Web",
             "transaction_date": datetime(2026, 6, 10, 15, 30), "amount": 850.0, "currency": "USD", "amount_usd": 850.0, "transaction_country": "USA"}
    routine = {"transaction_id": "T-ROUTINE", "customer_id": "CLI-9", "product_id": "PRD-9", "product_type": "Tarjeta Crédito", "channel": "App",
               "transaction_date": datetime(2026, 6, 14, 12, 0), "amount": 28.0, "currency": "USD", "amount_usd": 28.0}
    s_risky, top = scorer(risky, history, profile)
    s_routine, _ = scorer(routine, history, profile)
    assert 0.0 <= s_routine < s_risky <= 1.0
    assert 1 <= len(top) <= 3 and {"feature", "phrase", "value", "contribution"} <= set(top[0])
    assert all(t["feature"] in CONTRACT_V1 for t in top)


def test_orchestrator_uses_the_scorer_policy_threshold(bank_fixture_db, ops_store, owner_session):
    """A transferred score of 0.10 escalates when the bundle's percentile threshold is 0.05, and the handoff carries the threshold."""
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway import BankingToolGateway

    class Scorer:
        policy_threshold = 0.05

        def __call__(self, matched, history, profile):
            return 0.10, [{"feature": "amount_usd", "phrase": "Amount in USD", "value": 0.9, "contribution": 0.2}]

    orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=bank_fixture_db), ops=ops_store, risk_scorer=Scorer())
    cid = orchestrator.start_conversation(owner_session)["conversation_id"]
    turn = orchestrator.handle_message(owner_session, cid, "No reconozco un cargo de 80 dólares en Oxxo")
    assert turn.escalation_reason == "HIGH_FRAUD_RISK_SCORE"
    packet = ops_store.get_handoff(turn.handoff_id)["packet"]
    assert packet["risk_explanation"]["score"] == 0.10 and packet["risk_explanation"]["threshold"] == 0.05


def test_serving_reads_a_missing_usd_value_as_training_does():
    """load_bank_canonical passes amount_usd as stored, so a NULL scores as 0.0; serving must not read the local amount as USD."""
    from src.ml.bank_adapter import rows_to_canonical
    from src.ml.feature_contract import build_contract_features
    row = {"transaction_id": "T1", "transaction_date": "2026-06-12T14:22:00", "amount": 480000.0, "currency": "COP", "amount_usd": None,
           "product_id": "P1", "product_type": "Tarjeta Crédito"}
    feats = build_contract_features(rows_to_canonical(row, [row], {"country": "Colombia"}))
    assert feats.loc[feats["row_id"] == "T1", "amount_usd"].iloc[0] == 0.0


def test_load_scorer_picks_the_transfer_scorer_for_a_contract_bundle(competition_dir, bank_db, tmp_path):
    from src.api.dispute_routes import load_scorer
    train(competition_dir, tmp_path / "r", tmp_path / "ieee.joblib", lakehouse=bank_db, holdout_fraction_of_days=0.25)
    scorer = load_scorer(tmp_path / "ieee.joblib")
    assert isinstance(scorer, TransferRiskScorer) and 0.0 < scorer.policy_threshold <= 1.0
    assert load_scorer(tmp_path / "missing.joblib") is None


def test_train_logs_an_mlflow_run_with_params_metrics_and_reports(competition_dir, bank_db, tmp_path):
    """TQ-021: every training run is tracked in MLflow on a local file store; the JSON and Markdown reports and the bundle are its artifacts."""
    import mlflow

    tracking = f"sqlite:///{tmp_path / 'mlflow.db'}"
    report = train(competition_dir, tmp_path / "reports", tmp_path / "model.joblib", lakehouse=bank_db, holdout_fraction_of_days=0.25, percentile=90.0,
                   tracking_uri=tracking)
    assert report["mlflow"]["tracking_uri"] == tracking and report["mlflow"]["run_id"]
    client = mlflow.MlflowClient(tracking_uri=tracking)
    run = client.get_run(report["mlflow"]["run_id"])
    assert run.info.status == "FINISHED"
    assert client.get_experiment(run.info.experiment_id).name == "fraud_risk_transfer"
    assert run.data.params["contract_version"] == "1.1" and run.data.params["fraud_score_used"] == "False" and run.data.params["n_features"] == "19"
    assert run.data.params["percentile"] == "90.0" and run.data.params["threshold_kind"] == "percentile"
    assert run.data.metrics["test_roc_auc"] == pytest.approx(report["model"]["test"]["roc_auc"])
    assert run.data.metrics["threshold"] == pytest.approx(report["threshold"])
    assert run.data.metrics["bank_share_above_threshold"] == pytest.approx(report["bank_calibration"]["share_above_threshold"])
    assert run.data.metrics["ablation_without_card_aggregates_test_roc_auc"] == pytest.approx(report["ablations"]["without_card_aggregates"]["test"]["roc_auc"])
    assert run.data.tags["commit"] == report["commit"]
    artifacts = {a.path for a in client.list_artifacts(run.info.run_id)}
    assert {"fraud_risk_transfer.json", "fraud_risk_transfer.md", "model.joblib"} <= artifacts
    assert run.info.artifact_uri.startswith((tmp_path / "mlruns").resolve().as_uri())  # artifacts stay next to the store


def test_train_tracks_in_the_default_store_from_the_environment(competition_dir, tmp_path, monkeypatch):
    """Without an explicit tracking_uri the run goes to MLFLOW_TRACKING_URI (the test suite points it at a temporary SQLite file)."""
    store = f"sqlite:///{tmp_path / 'env' / 'mlflow.db'}"
    (tmp_path / "env").mkdir()
    monkeypatch.setenv("MLFLOW_TRACKING_URI", store)
    report = train(competition_dir, tmp_path / "reports", tmp_path / "model.joblib", holdout_fraction_of_days=0.25)
    assert report["mlflow"]["tracking_uri"] == store and (tmp_path / "env" / "mlflow.db").is_file() and (tmp_path / "env" / "mlruns").is_dir()


def test_competition_rows_that_share_a_timestamp_load_in_transaction_id_order(tmp_path):
    """20,000 rows on 50 timestamps, written in descending id order: the load must not depend on how the engine breaks the ties."""
    from src.ml.ieee_cis_adapter import load_competition
    n = 20_000
    rows = pd.DataFrame({"TransactionID": range(n - 1, -1, -1), "isFraud": 0, "TransactionDT": [86400 + (i % 50) for i in range(n)],
                         "TransactionAmt": 10.0, "card1": 1, "card6": "debit", "addr1": 100.0, "dist1": 0.0, "D1": 0,
                         **{m: "T" for m in ("M1", "M2", "M3", "M5", "M6", "M7", "M8", "M9")}, "M4": "M0"})
    rows.to_csv(tmp_path / "train_transaction.csv", index=False)
    loaded = load_competition(tmp_path)
    ids = loaded["row_id"].astype(int)
    assert loaded["ts"].is_monotonic_increasing
    assert (ids.groupby(loaded["ts"]).apply(lambda s: s.is_monotonic_increasing)).all()


def test_bank_rows_load_in_time_and_id_order(bank_db):
    from src.ml.bank_adapter import load_bank_canonical
    bank = load_bank_canonical(bank_db)
    order = bank[["ts", "row_id"]].apply(tuple, axis=1).tolist()
    assert order == sorted(order)
