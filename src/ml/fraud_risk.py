"""
Unrecognized-charge risk model without the fraud_score leak (brief decision 3, AGENTS.md section 8).

Features are pre-authorization behavior only: USD amount, velocity in 24 h and 7 days, ratio to the customer's
historical average, merchant category, channel, foreign country (names normalized), time of day on the bank's
processing clock (transaction_date minus 6 h) and account age. A rules-only baseline (amount over 1,000, card
not present, ratio over 3, foreign country) is scored on the same split. The split is by time (last days held
out); the decision threshold minimizes 10 x missed fraud + 1 x unnecessary verification on the training split.

Gradient boosting is scikit-learn's HistGradientBoostingClassifier (no new dependency); swapping in LightGBM is
a one-line change once the full history is loaded (team question TQ-022). Tracking is a JSON report per run.

    uv run python -m src.ml.fraud_risk --source data/lakehouse.duckdb --out reports/ml --model models/fraud_risk.joblib
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

CHANNELS = ["POS", "ATM", "Web", "App", "Branch", "Transfer"]
MERCHANT_CATEGORIES = ["Food", "Services", "Other", "Transport", "Entertainment", "Health", "Retail", "Travel", "Unknown"]
NUMERIC = ["amount_usd", "log_amount_usd", "velocity_24h_count", "velocity_24h_sum", "velocity_7d_count", "velocity_7d_sum",
           "ratio_to_historical_avg", "is_foreign_country", "hour_sin", "hour_cos", "account_age_days", "card_not_present"]
COUNTRIES = ["México", "Colombia", "Argentina"]
SEGMENTS = ["Premium", "Plus", "Basic", "Student"]
TRANSACTION_TYPES = ["Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment"]
FEATURES = (NUMERIC + [f"channel_{c}" for c in CHANNELS] + [f"merchant_{m}" for m in MERCHANT_CATEGORIES]
            + [f"country_{c}" for c in COUNTRIES] + [f"segment_{s}" for s in SEGMENTS] + [f"type_{t}" for t in TRANSACTION_TYPES])
COUNTRY_FIX = {"Mexico": "México"}
MISSED_FRAUD_COST = 10.0
UNNECESSARY_VERIFICATION_COST = 1.0

FEATURE_PHRASES = {
    "amount_usd": "Amount in USD", "log_amount_usd": "Amount in USD (log scale)", "velocity_24h_count": "Charges in the last 24 hours",
    "velocity_24h_sum": "Amount charged in the last 24 hours", "velocity_7d_count": "Charges in the last 7 days",
    "velocity_7d_sum": "Amount charged in the last 7 days", "ratio_to_historical_avg": "Amount versus the customer's average",
    "is_foreign_country": "Charge made outside the customer's country", "hour_sin": "Time of day (processing clock)",
    "hour_cos": "Time of day (processing clock)", "account_age_days": "Account age in days (tenure)", "card_not_present": "Card not present (Web or App)",
    **{f"country_{c}": f"Customer's country is {c}" for c in ["México", "Colombia", "Argentina"]},
    **{f"segment_{s}": f"Customer segment is {s}" for s in ["Premium", "Plus", "Basic", "Student"]},
    **{f"type_{t}": f"Transaction type is {t}" for t in ["Purchase", "Withdrawal", "Transfer", "Payment", "Deposit", "Adjustment"]},
}


def normalize_country(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return COUNTRY_FIX.get(str(value), str(value))


def build_features(tx: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    """tx needs transaction_id, customer_id, transaction_date, amount_usd, channel, merchant_category, transaction_country;
    customers needs customer_id, country, account_age_days and segment (tenure, country and segment are model inputs,
    team request of 27-Sep). Velocity uses the customer's earlier rows only."""
    cust_cols = ["customer_id", "country", "account_age_days"] + (["segment"] if "segment" in customers.columns else [])
    df = tx.merge(customers[cust_cols], on="customer_id", how="left")
    if "segment" not in df.columns:
        df["segment"] = None
    df["transaction_date"] = pd.to_datetime(df["transaction_date"])
    df["amount_usd"] = pd.to_numeric(df["amount_usd"], errors="coerce").fillna(0.0).clip(lower=0.0)
    df["log_amount_usd"] = np.log1p(df["amount_usd"])
    df = df.sort_values(["customer_id", "transaction_date"]).reset_index(drop=True)
    # Velocity over the customer's earlier rows only (vectorized: the full history has millions of rows).
    grouped = df.groupby("customer_id", sort=False)
    for window, label in (("24h", "24h"), ("7D", "7d")):
        rolled = grouped.rolling(window, on="transaction_date")["amount_usd"].agg(["count", "sum"]).reset_index(level=0, drop=True)
        rolled = rolled.sort_index()
        df[f"velocity_{label}_count"] = (rolled["count"].to_numpy() - 1).clip(min=0).astype(int)
        df[f"velocity_{label}_sum"] = (rolled["sum"].to_numpy() - df["amount_usd"].to_numpy()).clip(min=0.0)
    prior_count = grouped.cumcount().to_numpy()
    prior_sum = grouped["amount_usd"].cumsum().to_numpy() - df["amount_usd"].to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        hist_avg = np.where(prior_count > 0, prior_sum / np.maximum(prior_count, 1), np.nan)
        ratio = np.where((prior_count > 0) & (hist_avg > 0), df["amount_usd"].to_numpy() / np.where(hist_avg > 0, hist_avg, 1.0), 1.0)
    df["ratio_to_historical_avg"] = ratio
    tx_country = df["transaction_country"].map(normalize_country)
    cust_country = df["country"].map(normalize_country)
    df["is_foreign_country"] = ((tx_country.notna()) & (cust_country.notna()) & (tx_country != cust_country)).astype(float)
    local = df["transaction_date"] - timedelta(hours=6)
    hour = local.dt.hour + local.dt.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["account_age_days"] = pd.to_numeric(df["account_age_days"], errors="coerce").fillna(0.0)
    df["card_not_present"] = df["channel"].isin(["Web", "App"]).astype(float)
    for c in CHANNELS:
        df[f"channel_{c}"] = (df["channel"] == c).astype(float)
    cat = df["merchant_category"].fillna("Unknown").where(df["merchant_category"].isin(MERCHANT_CATEGORIES), "Other")
    cat = cat.where(df["merchant_category"].notna(), "Unknown")
    for m in MERCHANT_CATEGORIES:
        df[f"merchant_{m}"] = (cat == m).astype(float)
    for c in COUNTRIES:
        df[f"country_{c}"] = (cust_country == c).astype(float)
    for seg in SEGMENTS:
        df[f"segment_{seg}"] = (df["segment"] == seg).astype(float)
    tx_type = df["transaction_type"] if "transaction_type" in df.columns else pd.Series([None] * len(df), index=df.index)
    for t in TRANSACTION_TYPES:
        df[f"type_{t}"] = (tx_type == t).astype(float)
    return df


def rules_baseline_score(features: pd.DataFrame) -> np.ndarray:
    """Deterministic heuristics only, no fraud_score: each rule adds 0.25."""
    score = (features["amount_usd"] > 1000).astype(float) * 0.25
    score += features["card_not_present"] * 0.25
    score += (features["ratio_to_historical_avg"] > 3.0).astype(float) * 0.25
    score += features["is_foreign_country"] * 0.25
    return score.to_numpy()


def cost_threshold(y: np.ndarray, scores: np.ndarray) -> tuple[float, float]:
    """Threshold minimizing 10 x missed fraud + 1 x unnecessary verification; returns (threshold, cost)."""
    best_t, best_cost = 0.5, float("inf")
    for t in np.unique(np.concatenate([[0.0, 0.5, 0.70, 1.0], np.round(scores, 4)])):
        flagged = scores >= t
        cost = MISSED_FRAUD_COST * float(((~flagged) & (y == 1)).sum()) + UNNECESSARY_VERIFICATION_COST * float((flagged & (y == 0)).sum())
        if cost < best_cost or (cost == best_cost and t > best_t):
            best_t, best_cost = float(t), cost
    return best_t, best_cost


def _metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    flagged = scores >= threshold
    tp = int((flagged & (y == 1)).sum()); fp = int((flagged & (y == 0)).sum()); fn = int((~flagged & (y == 1)).sum())
    out = {"n": int(len(y)), "positives": int(y.sum()), "threshold": threshold, "true_positives": tp, "false_positives": fp,
           "missed_fraud": fn, "recall": (tp / (tp + fn)) if (tp + fn) else None, "precision": (tp / (tp + fp)) if (tp + fp) else None,
           "cost": MISSED_FRAUD_COST * fn + UNNECESSARY_VERIFICATION_COST * fp}
    if 0 < y.sum() < len(y):
        out["roc_auc"] = float(roc_auc_score(y, scores))
        out["pr_auc"] = float(average_precision_score(y, scores))
    else:
        out["roc_auc"] = out["pr_auc"] = None
    return out


def load_training_frame(source: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(str(source), read_only=True)
    try:
        tx = con.execute("""SELECT transaction_id, customer_id, transaction_date, process_date, amount_usd, channel,
                                   merchant_category, transaction_country, transaction_type, transaction_status, is_fraud
                            FROM gold_transactions""").df()
        customers = con.execute("SELECT customer_id, country, account_age_days, segment FROM gold_customers").df()
    finally:
        con.close()
    return tx, customers


def train(source: str | Path, out_dir: str | Path, model_path: str | Path, test_fraction_of_days: float = 0.35) -> dict[str, Any]:
    tx, customers = load_training_frame(source)
    df = build_features(tx, customers)
    df["is_fraud"] = df["is_fraud"].fillna(False).astype(int)
    days = sorted(pd.to_datetime(df["process_date"]).dt.date.unique())
    split_at = days[max(1, int(round(len(days) * (1 - test_fraction_of_days))))] if len(days) > 1 else days[0]
    is_test = pd.to_datetime(df["process_date"]).dt.date >= split_at
    train_df, test_df = df[~is_test], df[is_test]
    X_train, y_train = train_df[FEATURES].to_numpy(), train_df["is_fraud"].to_numpy()
    X_test, y_test = test_df[FEATURES].to_numpy(), test_df["is_fraud"].to_numpy()

    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=10,
                                           class_weight="balanced", random_state=7)
    degenerate = y_train.sum() == 0 or y_train.sum() == len(y_train)
    if degenerate:
        model = None
        train_scores = rules_baseline_score(train_df)
        test_scores = rules_baseline_score(test_df)
    else:
        model.fit(X_train, y_train)
        train_scores = model.predict_proba(X_train)[:, 1]
        test_scores = model.predict_proba(X_test)[:, 1] if len(X_test) else np.array([])
    threshold, _ = cost_threshold(y_train, train_scores)
    baseline_train = rules_baseline_score(train_df)
    baseline_threshold, _ = cost_threshold(y_train, baseline_train)
    report = {
        "run_at": datetime.utcnow().replace(microsecond=0).isoformat(), "source": str(source), "commit": _commit(),
        "algorithm": "sklearn.HistGradientBoostingClassifier (LightGBM stand-in, TQ-022)" if not degenerate else "none: no positives in the training split, rules baseline used",
        "features": FEATURES, "fraud_score_used": False,
        "split": {"by": "process_date", "train_days": [str(days[0]), str(min(d for d in days if d < split_at) if any(d < split_at for d in days) else days[0])],
                  "test_from": str(split_at), "train_rows": int(len(train_df)), "test_rows": int(len(test_df)),
                  "train_positives": int(y_train.sum()), "test_positives": int(y_test.sum())},
        "cost_weights": {"missed_fraud": MISSED_FRAUD_COST, "unnecessary_verification": UNNECESSARY_VERIFICATION_COST},
        "model": {"threshold": threshold, "train": _metrics(y_train, train_scores, threshold),
                  "test": _metrics(y_test, test_scores, threshold) if len(y_test) else None},
        "rules_baseline": {"threshold": baseline_threshold, "train": _metrics(y_train, baseline_train, baseline_threshold),
                           "test": _metrics(y_test, rules_baseline_score(test_df), baseline_threshold) if len(test_df) else None},
        "caveats": [],
    }
    if int(df["is_fraud"].sum()) < 50:
        report["caveats"].append(f"Only {int(df['is_fraud'].sum())} fraud rows in the source; the numbers are a pipeline check, not a result. Train on the full 2023 to 2026 history (TQ-013).")
    medians = {f: float(train_df[f].median()) if len(train_df) else 0.0 for f in FEATURES}
    joblib.dump({"model": model, "features": FEATURES, "medians": medians, "threshold": threshold, "report": report}, model_path)
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "fraud_risk.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "fraud_risk.md").write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, Any]) -> str:
    def block(name: str, part: dict[str, Any]) -> list[str]:
        rows = [f"## {name} (threshold {part['threshold']:.3f})", "", "| Split | n | Positives | Recall | Precision | Missed fraud | Unnecessary verifications | ROC AUC | PR AUC | Cost |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for split in ("train", "test"):
            m = part.get(split)
            if not m:
                continue
            fmt = lambda v: "not defined" if v is None else f"{v:.3f}"
            rows.append(f"| {split} | {m['n']} | {m['positives']} | {fmt(m['recall'])} | {fmt(m['precision'])} | {m['missed_fraud']} | {m['false_positives']} | {fmt(m['roc_auc'])} | {fmt(m['pr_auc'])} | {m['cost']:.0f} |")
        return rows + [""]
    lines = ["# Unrecognized-charge risk model", "", f"Run {report['run_at']}, commit {report['commit']}, source {report['source']}. Algorithm: {report['algorithm']}. fraud_score used: no.",
             f"Split by process_date: train {report['split']['train_rows']} rows ({report['split']['train_positives']} fraud), test from {report['split']['test_from']}: {report['split']['test_rows']} rows ({report['split']['test_positives']} fraud). "
             f"Threshold chosen on the training split by cost (missed fraud x{report['cost_weights']['missed_fraud']:.0f}, unnecessary verification x{report['cost_weights']['unnecessary_verification']:.0f}).", ""]
    lines += block("Gradient boosting", report["model"]) + block("Rules baseline", report["rules_baseline"])
    if report["caveats"]:
        lines += ["## Caveats", ""] + [f"- {c}" for c in report["caveats"]] + [""]
    return "\n".join(lines)


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


class RiskScorer:
    """Scores one charge for the orchestrator: (probability, top 3 ablation contributions in plain English)."""

    def __init__(self, model_path: str | Path = "models/fraud_risk.joblib"):
        bundle = joblib.load(model_path)
        self.model = bundle["model"]
        self.features = bundle["features"]
        self.medians = bundle["medians"]
        self.threshold = bundle["threshold"]

    def __call__(self, matched: dict[str, Any], history: list[dict[str, Any]], profile: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
        rows = [self._row(r, profile) for r in history if r.get("transaction_id") != matched.get("transaction_id")] + [self._row(matched, profile)]
        tx = pd.DataFrame(rows)
        customers = pd.DataFrame([{"customer_id": matched.get("customer_id", "current"), "country": profile.get("country"),
                                   "account_age_days": profile.get("account_age_days", 0), "segment": profile.get("segment")}])
        feats = build_features(tx, customers)
        current = feats[feats["transaction_id"] == matched.get("transaction_id")].iloc[-1]
        x = current[self.features].astype(float)
        score = self._predict(x.to_numpy())
        contributions = []
        for f in self.features:
            if f.startswith(("channel_", "merchant_", "country_", "segment_", "type_")):
                continue  # one-hot members are explained by the phrase of their group, not ablated one by one
            alt = x.copy(); alt[f] = self.medians.get(f, 0.0)
            delta = score - self._predict(alt.to_numpy())
            contributions.append({"feature": f, "phrase": FEATURE_PHRASES.get(f, f), "value": float(x[f]), "contribution": round(float(delta), 4)})
        contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
        return float(score), contributions[:3]

    def _predict(self, x: np.ndarray) -> float:
        if self.model is None:
            return float(rules_baseline_score(pd.DataFrame([dict(zip(self.features, x))]))[0])
        return float(self.model.predict_proba(x.reshape(1, -1))[0, 1])

    @staticmethod
    def _row(r: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        return {"transaction_id": r.get("transaction_id"), "customer_id": r.get("customer_id", "current"), "transaction_date": r.get("transaction_date"),
                "amount_usd": r.get("amount_usd", 0.0), "channel": r.get("channel"), "transaction_type": r.get("transaction_type"),
                "merchant_category": r.get("merchant_category"), "transaction_country": r.get("transaction_country", profile.get("country"))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the unrecognized-charge risk model without fraud_score.")
    parser.add_argument("--source", default="data/lakehouse.duckdb")
    parser.add_argument("--out", default="reports/ml")
    parser.add_argument("--model", default="models/fraud_risk.joblib")
    args = parser.parse_args()
    report = train(args.source, args.out, args.model)
    print(json.dumps({"model": report["model"], "rules_baseline": report["rules_baseline"], "caveats": report["caveats"]}, indent=2, default=str))


if __name__ == "__main__":
    main()
