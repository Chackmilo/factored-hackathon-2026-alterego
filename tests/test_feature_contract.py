"""Feature contract v1.1 (docs/specs/fraud-risk-model-v1-ieee-cis.md sections 4 and 10): one builder for both sources."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.ml.feature_contract import (
    CARD_AGGREGATES,
    CONTRACT_V1,
    CONTRACT_VERSION,
    DEPLOYABLE_V1,
    DISCRETE,
    LEAK_COLUMNS,
    NOT_DEPLOYABLE,
    QuantileRanker,
    build_contract_features,
)


def canonical(rows):
    base = datetime(2026, 6, 1, 10, 0)
    out = []
    for i, r in enumerate(rows):
        out.append({"row_id": f"R{i}", "uid": r.get("uid", "CARD-A"), "customer_uid": r.get("customer_uid", "CUST-1"),
                    "ts": base + timedelta(days=r.get("day", 0), hours=r.get("hour", 0)), "amount_usd": r.get("amount", 100.0),
                    "amount_local": r.get("amount_local", r.get("amount", 100.0)), "card_kind": r.get("card_kind", "credit"),
                    "card_age_days": r.get("card_age_days", 400), "address_distance_bucket": r.get("bucket", 0), "consistency_matches": r.get("consistency", 1.0)})
    return pd.DataFrame(out)


def test_contract_is_v1_1_with_twenty_features_and_no_leak():
    assert CONTRACT_VERSION == "1.1"
    assert len(CONTRACT_V1) == 20
    assert not set(CONTRACT_V1) & LEAK_COLUMNS
    assert "card_not_present" not in CONTRACT_V1 and "email_domain_freq" not in CONTRACT_V1 and "cards_per_customer" not in CONTRACT_V1
    assert set(DISCRETE) <= set(CONTRACT_V1) and set(CARD_AGGREGATES) <= set(CONTRACT_V1)


def test_builder_returns_every_contract_column_and_keeps_row_ids():
    feats = build_contract_features(canonical([{"amount": 50.0}, {"amount": 80.0, "day": 1}]))
    assert set(CONTRACT_V1) <= set(feats.columns)
    assert list(feats["row_id"]) == ["R0", "R1"]


def test_card_aggregates_use_earlier_rows_of_the_same_card_only():
    feats = build_contract_features(canonical([
        {"amount": 100.0, "day": 0}, {"amount": 300.0, "day": 2}, {"amount": 50.0, "day": 40}, {"uid": "CARD-B", "amount": 999.0, "day": 1},
    ])).set_index("row_id")
    assert feats.loc["R0", "tx_count_card_7d"] == 0 and np.isnan(feats.loc["R0", "days_since_prev_tx_card"])
    assert feats.loc["R1", "tx_count_card_7d"] == 1 and feats.loc["R1", "days_since_prev_tx_card"] == pytest.approx(2.0)
    assert feats.loc["R1", "amount_mean_card_hist"] == pytest.approx(100.0) and feats.loc["R1", "tx_sum_card_7d"] == pytest.approx(100.0)
    assert feats.loc["R2", "tx_count_card_7d"] == 0 and feats.loc["R2", "tx_count_card_30d"] == 0 and feats.loc["R2", "amount_mean_card_hist"] == pytest.approx(200.0)
    assert feats.loc["R3", "tx_count_card_30d"] == 0  # another card, untouched by CARD-A
    assert feats.loc["R2", "ratio_to_historical_avg"] == pytest.approx(50.0 / ((100 + 300 + 999) / 3))  # customer-level mean of earlier rows


def test_no_look_ahead_a_later_row_does_not_change_an_earlier_row():
    rows = [{"amount": 100.0, "day": 0}, {"amount": 120.0, "day": 3}]
    before = build_contract_features(canonical(rows)).set_index("row_id").loc["R1", CONTRACT_V1]
    after = build_contract_features(canonical(rows + [{"amount": 5000.0, "day": 4}])).set_index("row_id").loc["R1", CONTRACT_V1]
    pd.testing.assert_series_equal(before, after)


def test_time_and_kind_features():
    feats = build_contract_features(canonical([{"hour": 4, "card_kind": "debit", "amount_local": 10.25}, {"hour": 0, "card_kind": "account", "amount_local": 10.0, "day": 1}])).set_index("row_id")
    assert feats.loc["R0", "card_kind_debit"] == 1 and feats.loc["R0", "card_kind_credit"] == 0 and feats.loc["R0", "amount_has_cents"] == 1
    assert feats.loc["R1", "card_kind_debit"] == 0 and feats.loc["R1", "card_kind_credit"] == 0 and feats.loc["R1", "amount_has_cents"] == 0
    assert feats.loc["R0", "hour_sin"] == pytest.approx(np.sin(2 * np.pi * 14 / 24))  # base hour 10 plus 4
    assert feats.loc["R0", "day_of_week"] == 0  # 2026-06-01 is a Monday


def test_quantile_ranker_maps_continuous_features_to_percentiles_and_leaves_discrete_alone():
    df = pd.DataFrame({"amount_usd": [10.0, 20.0, 30.0, 40.0, np.nan], "card_kind_credit": [1, 0, 1, 0, 1]})
    r = QuantileRanker(continuous=["amount_usd"]).fit(df)
    out = r.transform(pd.DataFrame({"amount_usd": [5.0, 25.0, 100.0, np.nan], "card_kind_credit": [1, 1, 0, 0]}))
    assert out["amount_usd"].tolist() == pytest.approx([0.0, 0.5, 1.0, 0.5], abs=0.13)  # nulls take the median before ranking
    assert out["card_kind_credit"].tolist() == [1, 1, 0, 0]
    assert out["amount_usd"].between(0, 1).all()


def test_deployable_set_is_the_contract_minus_card_age():
    """Team decision of 29-Sep: train only on what the deployed app can compute from the serving copy at scoring time."""
    assert set(DEPLOYABLE_V1) == set(CONTRACT_V1) - {"card_age_days"}
    assert "card_age_days" in NOT_DEPLOYABLE and "independent" in NOT_DEPLOYABLE["card_age_days"]
