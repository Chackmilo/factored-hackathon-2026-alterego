"""
Feature contract v1.2 for the fraud risk transfer (docs/specs/fraud-risk-model-v1-ieee-cis.md, sections 4 and 10).

One builder computes the same features from a canonical frame, whichever source filled it (the IEEE-CIS competition
through src/ml/ieee_cis_adapter.py, the bank through src/ml/bank_adapter.py). Every per-card aggregate uses the
card's earlier rows only, so a served charge never looks ahead. The trainer uses DEPLOYABLE_V1: the contract minus
the features the deployed app cannot trust at scoring time (team decision of 29-Sep: train only on what deploy can use).

Canonical columns: row_id, uid (the card), customer_uid, ts (event time on the bank's processing clock), amount_usd,
amount_local, card_kind (credit, debit, account or None), card_age_days, address_distance_bucket (0 same city, 1 same
country, 2 abroad), consistency_matches (share of match checks passed, 0 to 1).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

CONTRACT_VERSION = "1.2"
# 1.2 (TQ-043, 5-Oct): a card spread or a window sum that is only floating-point residue counts as zero. In 1.1 equal earlier
# amounts left a variance near 1e-12, and dividing by its root gave z-scores of hundreds of millions.
SPREAD_EPSILON = 1e-6  # a spread under this share of the mean (or of 1 USD) is residue, far below a one-cent difference
SUM_EPSILON = 1e-6  # USD; amounts carry at most three decimals
CANONICAL_COLUMNS = ["row_id", "uid", "customer_uid", "ts", "amount_usd", "amount_local", "card_kind", "card_age_days",
                     "address_distance_bucket", "consistency_matches"]
CARD_AGGREGATES = ["days_since_prev_tx_card", "tx_count_card_1d", "tx_count_card_7d", "tx_count_card_30d", "tx_sum_card_7d",
                   "amount_mean_card_hist", "amount_std_card_hist", "amount_zscore_card", "ratio_to_historical_avg"]
DISCRETE = ["amount_has_cents", "day_of_week", "card_kind_credit", "card_kind_debit", "address_distance_bucket", "consistency_matches"]
CONTRACT_V1 = (["amount_usd", "log_amount_usd", "amount_has_cents", "hour_sin", "hour_cos", "day_of_week", "card_kind_credit",
                "card_kind_debit", "card_age_days"] + CARD_AGGREGATES + ["address_distance_bucket", "consistency_matches"])
NOT_DEPLOYABLE = {
    "card_age_days": "bank product opening dates are independent of the charges (18.71% of charges predate them, AGENTS.md section 7), "
                     "so the value at scoring time is noise",
}
DEPLOYABLE_V1 = [f for f in CONTRACT_V1 if f not in NOT_DEPLOYABLE]
CONTINUOUS = [f for f in CONTRACT_V1 if f not in DISCRETE]
LEAK_COLUMNS = {"is_fraud", "fraud_score", "isFraud", "transaction_status", "response_code", "resolution", "compensation_granted"}

FEATURE_PHRASES = {
    "amount_usd": "Amount in USD", "log_amount_usd": "Amount in USD (log scale)", "amount_has_cents": "Amount with cents",
    "hour_sin": "Time of day (processing clock)", "hour_cos": "Time of day (processing clock)", "day_of_week": "Day of the week",
    "card_kind_credit": "Product is a credit card", "card_kind_debit": "Product is a debit card", "card_age_days": "Card age in days",
    "days_since_prev_tx_card": "Days since the card's previous charge", "tx_count_card_1d": "Charges of the card in the last day",
    "tx_count_card_7d": "Charges of the card in the last 7 days", "tx_count_card_30d": "Charges of the card in the last 30 days",
    "tx_sum_card_7d": "Amount charged to the card in the last 7 days", "amount_mean_card_hist": "The card's usual charge amount",
    "amount_std_card_hist": "How much the card's amounts vary", "amount_zscore_card": "Amount versus the card's usual amounts",
    "ratio_to_historical_avg": "Amount versus the customer's average", "address_distance_bucket": "Charge location versus the customer's city and country",
    "consistency_matches": "Consistency of country, city and currency with the customer's profile",
}


def _window_stats(df: pd.DataFrame, window_seconds: int) -> tuple[np.ndarray, np.ndarray]:
    """Count and sum of the card's rows in (t - window, t], current row included; the caller removes it.

    df is sorted by uid then ts. Rows are keyed by card code and seconds so one searchsorted finds the window start."""
    codes = pd.factorize(df["uid"])[0].astype(np.int64)
    seconds = (df["ts"].astype("int64") // 10**9).to_numpy(np.int64)
    key = codes * np.int64(10**11) + seconds
    start = np.searchsorted(key, key - np.int64(window_seconds), side="right")
    idx = np.arange(len(df))
    csum = np.concatenate([[0.0], np.cumsum(df["amount_usd"].to_numpy(float))])
    return (idx - start + 1).astype(float), csum[idx + 1] - csum[start]


def build_contract_features(frame: pd.DataFrame) -> pd.DataFrame:
    """The contract columns appended to the canonical frame, rows returned in their original order."""
    df = frame.copy()
    df["_order"] = np.arange(len(df))
    df["ts"] = pd.to_datetime(df["ts"]).astype("datetime64[ns]")
    if "customer_uid" not in df.columns:
        df["customer_uid"] = df["uid"]
    df["customer_uid"] = df["customer_uid"].where(df["customer_uid"].notna(), df["uid"])
    df["amount_usd"] = pd.to_numeric(df["amount_usd"], errors="coerce").fillna(0.0).clip(lower=0.0)
    df["log_amount_usd"] = np.log1p(df["amount_usd"])
    local = pd.to_numeric(df.get("amount_local"), errors="coerce").fillna(df["amount_usd"]) if "amount_local" in df.columns else df["amount_usd"]
    df["amount_has_cents"] = (((local * 100).round() % 100) != 0).astype(int)
    hour = df["ts"].dt.hour + df["ts"].dt.minute / 60.0
    df["hour_sin"], df["hour_cos"] = np.sin(2 * np.pi * hour / 24.0), np.cos(2 * np.pi * hour / 24.0)
    df["day_of_week"] = df["ts"].dt.dayofweek.astype(int)
    kind = df["card_kind"].astype(str).str.lower() if "card_kind" in df.columns else pd.Series("", index=df.index)
    df["card_kind_credit"] = (kind == "credit").astype(int)
    df["card_kind_debit"] = (kind == "debit").astype(int)
    df["card_age_days"] = pd.to_numeric(df.get("card_age_days"), errors="coerce").clip(lower=0) if "card_age_days" in df.columns else np.nan
    for c in ("address_distance_bucket", "consistency_matches"):
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan

    # Per-card aggregates over earlier rows only (sorted by card and time; the current row is subtracted).
    df = df.sort_values(["uid", "ts"], kind="mergesort").reset_index(drop=True)
    amount = df["amount_usd"].to_numpy()
    g = df.groupby("uid", sort=False)
    for window, label in ((86400, "1d"), (7 * 86400, "7d"), (30 * 86400, "30d")):
        count, total = _window_stats(df, window)
        df[f"tx_count_card_{label}"] = (count - 1).clip(min=0).astype(int)
        if label == "7d":
            earlier = (total - amount).clip(min=0.0)
            df["tx_sum_card_7d"] = np.where(earlier < SUM_EPSILON, 0.0, earlier)
    prior_n = g.cumcount().to_numpy().astype(float)
    prior_sum = g["amount_usd"].cumsum().to_numpy() - amount
    prior_sq = (df["amount_usd"] ** 2).groupby(df["uid"], sort=False).cumsum().to_numpy() - amount ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.where(prior_n > 0, prior_sum / np.maximum(prior_n, 1), np.nan)
        var = np.where(prior_n > 1, (prior_sq - prior_n * mean ** 2) / np.maximum(prior_n - 1, 1), np.nan)
        std = np.sqrt(np.clip(var, 0, None))
        std = np.where(std <= SPREAD_EPSILON * np.maximum(np.abs(mean), 1.0), 0.0, std)  # NaN stays NaN: no spread known yet
        z = np.where((prior_n >= 3) & (std > 0), (amount - mean) / np.where(std > 0, std, 1.0), 0.0)
    df["amount_mean_card_hist"], df["amount_std_card_hist"], df["amount_zscore_card"] = mean, std, z
    df["days_since_prev_tx_card"] = (df["ts"] - g["ts"].shift(1)).dt.total_seconds() / 86400.0

    # Ratio to the customer's earlier average (all the customer's cards).
    dc = df.sort_values(["customer_uid", "ts"], kind="mergesort")
    gc = dc.groupby("customer_uid", sort=False)
    c_n = gc.cumcount().to_numpy().astype(float)
    c_sum = gc["amount_usd"].cumsum().to_numpy() - dc["amount_usd"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        c_mean = np.where(c_n > 0, c_sum / np.maximum(c_n, 1), np.nan)
        ratio = np.where((c_n > 0) & (c_mean > 0), dc["amount_usd"].to_numpy() / np.where(c_mean > 0, c_mean, 1.0), 1.0)
    df.loc[dc.index, "ratio_to_historical_avg"] = ratio
    return df.sort_values("_order").drop(columns=["_order"]).reset_index(drop=True)


class QuantileRanker:
    """Per-source percentile ranks for the continuous features (spec section 10.1); discrete features pass through.

    fit() stores a 1,001-point quantile grid and the median per feature; transform() fills nulls with the median and
    maps each value to its percentile on the grid, so the served bank charge is ranked against the bank's own window."""

    GRID = np.linspace(0.0, 1.0, 1001)

    def __init__(self, continuous: list[str]):
        self.continuous = list(continuous)
        self.grids: dict[str, np.ndarray] = {}
        self.medians: dict[str, float] = {}

    def fit(self, df: pd.DataFrame) -> QuantileRanker:
        for f in self.continuous:
            if f not in df.columns:
                continue
            x = pd.to_numeric(df[f], errors="coerce").dropna().to_numpy(float)
            if len(x) == 0:
                x = np.array([0.0])
            self.grids[f] = np.quantile(x, self.GRID)
            self.medians[f] = float(np.median(x))
        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for f, grid in self.grids.items():
            if f not in out.columns:
                continue
            x = pd.to_numeric(out[f], errors="coerce").fillna(self.medians[f]).to_numpy(float)
            lo = np.searchsorted(grid, x, side="left")
            hi = np.searchsorted(grid, x, side="right")
            out[f] = np.clip((lo + hi) / 2.0 / len(grid), 0.0, 1.0)  # ties take the middle of their run
        return out
