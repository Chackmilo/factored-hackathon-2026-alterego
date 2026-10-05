"""EDA of the served risk features: statistics per source, one chart per feature, observed against predicted on the competition."""
import numpy as np
import pandas as pd

from src.ml.feature_contract import DEPLOYABLE_V1, build_contract_features
from src.ml.ieee_cis_adapter import holdout_mask
from src.ml.risk_feature_eda import (
    calibration_table,
    daily_observed_expected,
    feature_stats,
    plot_feature,
)


def _features(n: int = 600, seed: int = 3) -> pd.DataFrame:
    """Canonical rows of 40 cards over 30 days, with a label that follows the amount."""
    rng = np.random.default_rng(seed)
    amount = np.round(rng.lognormal(4.0, 1.0, n), 2)
    frame = pd.DataFrame({
        "row_id": [f"R{i}" for i in range(n)], "uid": rng.integers(0, 40, n).astype(str),
        "ts": pd.Timestamp("2026-05-01") + pd.to_timedelta(rng.integers(0, 30 * 86400, n), unit="s"),
        "amount_usd": amount, "amount_local": amount, "card_kind": rng.choice(["credit", "debit"], n),
        "card_age_days": rng.integers(0, 900, n).astype(float), "address_distance_bucket": rng.choice([0.0, 1.0, 2.0, np.nan], n),
        "consistency_matches": rng.choice([0.0, 0.5, 1.0], n), "label": (amount > np.quantile(amount, 0.9)).astype(int),
    })
    frame["customer_uid"] = frame["uid"]
    return build_contract_features(frame)


def test_feature_stats_gives_min_max_and_mean_for_each_of_the_19_features():
    feats = _features()
    stats = feature_stats(feats, DEPLOYABLE_V1)
    assert [s["feature"] for s in stats] == list(DEPLOYABLE_V1) and len(stats) == 19
    amount = next(s for s in stats if s["feature"] == "amount_usd")
    assert amount["min"] == float(feats["amount_usd"].min())
    assert amount["max"] == float(feats["amount_usd"].max())
    assert amount["mean"] == float(feats["amount_usd"].mean())
    assert amount["n"] == len(feats) and amount["null_share"] == 0.0


def test_feature_stats_counts_nulls_and_splits_the_mean_by_label():
    feats = _features()
    stats = {s["feature"]: s for s in feature_stats(feats, DEPLOYABLE_V1, label="label")}
    first_rows = stats["days_since_prev_tx_card"]  # the first charge of each card has no previous one
    assert first_rows["nulls"] == int(feats["days_since_prev_tx_card"].isna().sum()) > 0
    assert first_rows["null_share"] == first_rows["nulls"] / len(feats)
    assert stats["amount_usd"]["mean_label_1"] > stats["amount_usd"]["mean_label_0"]


def test_feature_stats_of_a_feature_without_values_has_no_numbers():
    feats = _features()
    feats["address_distance_bucket"] = np.nan
    row = next(s for s in feature_stats(feats, DEPLOYABLE_V1) if s["feature"] == "address_distance_bucket")
    assert row["null_share"] == 1.0 and row["min"] is None and row["max"] is None and row["mean"] is None


def test_calibration_table_bins_cover_every_row_and_keep_the_positives():
    rng = np.random.default_rng(5)
    scores = rng.uniform(0, 1, 1000)
    y = (rng.uniform(0, 1, 1000) < scores).astype(int)
    table = calibration_table(y, scores, bins=10)
    assert len(table) == 10 and sum(b["n"] for b in table) == 1000 and sum(b["positives"] for b in table) == int(y.sum())
    assert [b["mean_predicted"] for b in table] == sorted(b["mean_predicted"] for b in table)
    assert table[-1]["observed_rate"] > table[0]["observed_rate"]


def test_daily_observed_expected_adds_up_to_the_totals():
    feats = _features()
    scores = np.full(len(feats), 0.25)
    days = daily_observed_expected(feats["ts"], feats["label"].to_numpy(int), scores)
    assert sum(d["observed"] for d in days) == int(feats["label"].sum())
    assert abs(sum(d["expected"] for d in days) - 0.25 * len(feats)) < 1e-6
    assert [d["day"] for d in days] == sorted(d["day"] for d in days)


def test_holdout_mask_takes_the_last_fifth_of_the_days():
    feats = _features()
    is_test, days, split_at = holdout_mask(feats["ts"], 0.2)
    assert len(days) == 30 and split_at == days[24]
    assert (feats["ts"].dt.date[is_test] >= split_at).all() and (feats["ts"].dt.date[~is_test] < split_at).all()


def test_plot_feature_writes_one_chart_per_feature(tmp_path):
    competition, bank = _features(seed=3), _features(seed=4)
    for i, feature in enumerate(DEPLOYABLE_V1, start=1):
        path = plot_feature(feature, competition, bank, tmp_path / f"{i:02d}_{feature}.png")
        assert path.exists() and path.stat().st_size > 5000
    assert len(list(tmp_path.glob("*.png"))) == 19
