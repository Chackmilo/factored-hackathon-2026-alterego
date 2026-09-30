"""
Fraud risk score transferred from the IEEE-CIS competition (docs/specs/fraud-risk-model-v1-ieee-cis.md).

Training data is the competition (590,540 labeled card-not-present transactions); the bank label is random (discussion
doc sections 5 and 6) and is used once, to report its flat agreement. Features are DEPLOYABLE_V1 of the contract: only
what the deployed app can compute from the serving copy at scoring time (team decision of 29-Sep). Continuous features
are per-source percentile ranks (the sources stay separable under any encoding, notebook 05), so the escalation
threshold is a percentile of the bank's own serving window (Web and App charges), never the competition's probability.

    uv run python -m src.ml.fraud_risk_transfer --competition data/kaggle --lakehouse data/lakehouse_full.duckdb \
        --out reports/ml --model models/fraud_risk_ieee.joblib

Every run is tracked in MLflow (TQ-021, decided 29-Sep): parameters, metrics, the commit tag, and the JSON and Markdown
reports plus the model bundle as artifacts. The store is local and needs no server: MLFLOW_TRACKING_URI, else
sqlite:///mlflow.db in the working directory, with the artifacts in mlruns/ next to it (both git-ignored). Browse with
`uv run mlflow ui --backend-store-uri sqlite:///mlflow.db` after installing the full `mlflow` package (skinny has no UI).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
import mlflow  # noqa: E402  (the hint switch has to precede the import)
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from src.ml.bank_adapter import load_bank_canonical, rows_to_canonical
from src.ml.feature_contract import (
    CARD_AGGREGATES,
    CONTRACT_VERSION,
    DEPLOYABLE_V1,
    DISCRETE,
    FEATURE_PHRASES,
    LEAK_COLUMNS,
    NOT_DEPLOYABLE,
    QuantileRanker,
    build_contract_features,
)
from src.ml.fraud_risk import _metrics, cost_threshold
from src.ml.ieee_cis_adapter import load_competition

DEFAULT_PERCENTILE = 98.0
MLFLOW_EXPERIMENT = "fraud_risk_transfer"
FIT_PARAMS = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 40, "random_state": 7}
ABLATIONS = {"without_card_aggregates": CARD_AGGREGATES, "without_discrete_block": DISCRETE}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _fit(X: np.ndarray, y: np.ndarray) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**FIT_PARAMS).fit(X, y)


DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"


def resolve_tracking_uri(tracking_uri: str | None = None) -> str:
    """Explicit argument, else MLFLOW_TRACKING_URI, else a SQLite file in the working directory (MLflow 3 retired the plain file store)."""
    return tracking_uri or os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_TRACKING_URI


def artifact_root_for(tracking_uri: str) -> str:
    """Artifacts live in an mlruns/ directory next to the SQLite file, so a temporary store keeps its artifacts with it."""
    if tracking_uri.startswith("sqlite:///"):
        return (Path(tracking_uri[len("sqlite:///"):]).resolve().parent / "mlruns").as_uri()
    return Path("mlruns").resolve().as_uri()


def _experiment_id(name: str, tracking_uri: str) -> str:
    existing = mlflow.get_experiment_by_name(name)
    return existing.experiment_id if existing else mlflow.create_experiment(name, artifact_location=artifact_root_for(tracking_uri))


def _flat_metrics(prefix: str, block: dict[str, Any] | None) -> dict[str, float]:
    return {f"{prefix}_{k}": float(v) for k, v in (block or {}).items() if isinstance(v, (int, float)) and v is not None}


def _log_run(report: dict[str, Any], files: list[Path], params: dict[str, Any]) -> None:
    """Parameters, metrics and tags of one training run; the reports and the bundle go in as artifacts."""
    mlflow.log_params({k: str(v) for k, v in params.items()})
    metrics = {**_flat_metrics("train", report["model"]["train"]), **_flat_metrics("test", report["model"]["test"]),
               "cost_threshold": float(report["model"]["cost_threshold"]), "threshold": float(report["threshold"])}
    for name, ablation in report["ablations"].items():
        metrics.update(_flat_metrics(f"ablation_{name}_test", ablation["test"]))
    bank = report["bank_calibration"]
    if bank:
        metrics.update({"bank_charges_scored": float(bank["charges_scored"]), "bank_is_fraud_positives": float(bank["is_fraud_positives"])})
        if bank["share_above_threshold"] is not None:
            metrics["bank_share_above_threshold"] = float(bank["share_above_threshold"])
        metrics.update(_flat_metrics("bank_is_fraud", bank["is_fraud_agreement"]))
    mlflow.log_metrics(metrics)
    mlflow.set_tags({"commit": report["commit"], "contract_version": report["contract_version"], "threshold_kind": report["threshold_kind"]})
    for f in files:
        mlflow.log_artifact(str(f))


def _auc_block(y: np.ndarray, s: np.ndarray) -> dict[str, float | None]:
    two = len(np.unique(y)) == 2
    return {"roc_auc": float(roc_auc_score(y, s)) if two else None, "pr_auc": float(average_precision_score(y, s)) if two else None}


def train(competition: str | Path, out_dir: str | Path, model_path: str | Path, lakehouse: str | Path | None = None,
          holdout_fraction_of_days: float = 0.2, percentile: float = DEFAULT_PERCENTILE, limit: int | None = None,
          channels: tuple[str, ...] = ("Web", "App"), window_days: int = 60, tracking_uri: str | None = None) -> dict[str, Any]:
    uri = resolve_tracking_uri(tracking_uri)
    mlflow.set_tracking_uri(uri)
    run = mlflow.start_run(experiment_id=_experiment_id(MLFLOW_EXPERIMENT, uri), run_name=f"contract-{CONTRACT_VERSION}-{_commit()}")
    try:
        report = _train(competition, out_dir, model_path, lakehouse, holdout_fraction_of_days, percentile, limit, channels, window_days,
                        mlflow_info={"tracking_uri": uri, "experiment": MLFLOW_EXPERIMENT, "run_id": run.info.run_id})
    except BaseException:
        mlflow.end_run(status="FAILED")
        raise
    mlflow.end_run(status="FINISHED")
    return report


def _train(competition, out_dir, model_path, lakehouse, holdout_fraction_of_days, percentile, limit, channels, window_days,
           mlflow_info: dict[str, str]) -> dict[str, Any]:
    features = list(DEPLOYABLE_V1)
    assert not set(features) & LEAK_COLUMNS
    continuous = [f for f in features if f not in DISCRETE]
    canon = load_competition(competition, limit=limit)
    feats = build_contract_features(canon)
    days = sorted(feats["ts"].dt.date.unique())
    split_at = days[max(1, int(round(len(days) * (1 - holdout_fraction_of_days))))] if len(days) > 1 else days[0]
    is_test = feats["ts"].dt.date >= split_at
    tr, te = feats[~is_test], feats[is_test]
    y_tr, y_te = tr["label"].to_numpy(int), te["label"].to_numpy(int)
    ranker_comp = QuantileRanker(continuous).fit(tr[features])
    X_tr, X_te = ranker_comp.transform(tr[features]).to_numpy(float), ranker_comp.transform(te[features]).to_numpy(float)
    model = _fit(X_tr, y_tr)
    s_tr, s_te = model.predict_proba(X_tr)[:, 1], model.predict_proba(X_te)[:, 1]
    cost_t, _ = cost_threshold(y_tr, s_tr)
    ablations = {}
    for name, dropped in ABLATIONS.items():
        keep = [i for i, f in enumerate(features) if f not in dropped]
        m = _fit(X_tr[:, keep], y_tr)
        ablations[name] = {"dropped": [f for f in features if f in dropped], "test": _auc_block(y_te, m.predict_proba(X_te[:, keep])[:, 1])}

    bank_calibration, ranker_bank = None, None
    if lakehouse is not None:
        bank = load_bank_canonical(lakehouse, channels=channels, window_days=window_days)
        bf = build_contract_features(bank)
        scope = bf[bf["in_scope"]]
        ranker_bank = QuantileRanker(continuous).fit(scope[features])
        s_bank = model.predict_proba(ranker_bank.transform(scope[features]).to_numpy(float))[:, 1] if len(scope) else np.array([])
        threshold = float(np.percentile(s_bank, percentile)) if len(s_bank) else float(np.percentile(s_te, percentile))
        yb = scope["label"].to_numpy(int)
        bank_calibration = {"lakehouse": str(lakehouse), "anchor": bank.attrs.get("anchor"), "window_days": window_days, "channels": list(channels),
                            "charges_scored": int(len(scope)), "percentile": float(percentile), "threshold": threshold,
                            "share_above_threshold": float((s_bank >= threshold).mean()) if len(s_bank) else None,
                            "is_fraud_positives": int(yb.sum()), "is_fraud_agreement": _auc_block(yb, s_bank) if len(s_bank) else None,
                            "score_quantiles": {str(q): float(np.percentile(s_bank, q)) for q in (50, 90, 95, 98, 99)} if len(s_bank) else None}
        threshold_kind = "percentile"
    else:
        threshold = float(np.percentile(s_te, percentile))
        threshold_kind = "percentile_competition_holdout"

    report = {
        "run_at": datetime.utcnow().replace(microsecond=0).isoformat(), "commit": _commit(), "competition": str(competition),
        "contract_version": CONTRACT_VERSION, "features": features, "not_deployable_excluded": NOT_DEPLOYABLE, "fraud_score_used": False,
        "algorithm": "sklearn.HistGradientBoostingClassifier on per-source percentile ranks (LightGBM stand-in, TQ-022)",
        "split": {"by": "competition day", "days": len(days), "test_from_day_index": days.index(split_at), "train_rows": int(len(tr)), "test_rows": int(len(te)),
                  "train_positives": int(y_tr.sum()), "test_positives": int(y_te.sum())},
        "model": {"cost_threshold": cost_t, "train": _metrics(y_tr, s_tr, cost_t), "test": _metrics(y_te, s_te, cost_t) if len(y_te) else None},
        "ablations": ablations, "bank_calibration": bank_calibration, "threshold": threshold, "threshold_kind": threshold_kind,
        "mlflow": mlflow_info,
        "caveats": ["The competition holds card-not-present rows only: the score is served on Web and App charges, the rules baseline covers the rest.",
                    "The bank label is random (discussion doc sections 5 and 6); its agreement is reported, never optimized."],
    }
    medians = {f: float(np.nanmedian((ranker_bank or ranker_comp).transform(tr[features])[f].to_numpy(float))) for f in features}
    joblib.dump({"model": model, "features": features, "ranker": ranker_bank or ranker_comp, "ranker_competition": ranker_comp, "medians": medians,
                 "threshold": threshold, "threshold_kind": threshold_kind, "contract_version": CONTRACT_VERSION, "report": report}, model_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fraud_risk_transfer.json").write_text(json.dumps(report, indent=2, default=str))
    (out / "fraud_risk_transfer.md").write_text(render_markdown(report))
    _log_run(report, [out / "fraud_risk_transfer.json", out / "fraud_risk_transfer.md", Path(model_path)],
             params={"contract_version": CONTRACT_VERSION, "n_features": len(features), "features": ",".join(features), "fraud_score_used": False,
                     "algorithm": "sklearn.HistGradientBoostingClassifier", **FIT_PARAMS, "competition": str(competition), "limit": limit,
                     "lakehouse": lakehouse, "channels": ",".join(channels), "window_days": window_days, "holdout_fraction_of_days": holdout_fraction_of_days,
                     "percentile": percentile, "threshold_kind": threshold_kind})
    return report


def render_markdown(r: dict[str, Any]) -> str:
    def fmt(v):
        return "not defined" if v is None else f"{v:.3f}"
    lines = [f"# Fraud risk transfer report ({r['run_at']}, commit {r['commit']})", "",
             f"Contract v{r['contract_version']}, {len(r['features'])} deployable features, fraud_score used: no. {r['algorithm']}.", "",
             "## Competition time split", "", "| Split | n | Positives | ROC AUC | PR AUC | Recall at cost threshold | Precision |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for split in ("train", "test"):
        m = r["model"].get(split)
        if m:
            lines.append(f"| {split} | {m['n']:,} | {m['positives']:,} | {fmt(m.get('roc_auc'))} | {fmt(m.get('pr_auc'))} | {fmt(m.get('recall'))} | {fmt(m.get('precision'))} |")
    lines += ["", "## Ablations (holdout)", "", "| Ablation | Dropped | ROC AUC | PR AUC |", "| --- | --- | --- | --- |"]
    for name, a in r["ablations"].items():
        lines.append(f"| {name} | {', '.join(a['dropped'])} | {fmt(a['test']['roc_auc'])} | {fmt(a['test']['pr_auc'])} |")
    b = r.get("bank_calibration")
    lines += ["", "## Bank calibration", ""]
    if b:
        agr = b.get("is_fraud_agreement") or {}
        lines += [f"{b['charges_scored']:,} charges on {', '.join(b['channels'])} in the {b['window_days']} days to {b['anchor']}; "
                  f"threshold = percentile {b['percentile']:.0f} of their scores = {b['threshold']:.4f}; share above: {fmt(b['share_above_threshold'])}; "
                  f"agreement with is_fraud ({b['is_fraud_positives']} flags): ROC AUC {fmt(agr.get('roc_auc'))}."]
    else:
        lines += [f"No lakehouse given: threshold = percentile of the competition holdout scores ({r['threshold']:.4f})."]
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in r["caveats"]]
    return "\n".join(lines) + "\n"


class TransferRiskScorer:
    """Same signature as src.ml.fraud_risk.RiskScorer: (matched, history, profile) -> (score, top 3 contributions)."""

    def __init__(self, model_path: str | Path = "models/fraud_risk_ieee.joblib"):
        bundle = joblib.load(model_path)
        self.model, self.features, self.ranker = bundle["model"], bundle["features"], bundle["ranker"]
        self.medians, self.threshold, self.threshold_kind = bundle["medians"], bundle["threshold"], bundle["threshold_kind"]
        self.policy_threshold = float(self.threshold)  # read by the orchestrator for POL-ESC-ML-RISK

    def __call__(self, matched: dict[str, Any], history: list[dict[str, Any]], profile: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
        feats = build_contract_features(rows_to_canonical(matched, history, profile))
        current = feats[feats["row_id"] == matched.get("transaction_id")].iloc[-1:]
        x = self.ranker.transform(current[self.features]).iloc[0].astype(float)
        x = x.fillna(pd.Series(self.medians))
        score = self._predict(x.to_numpy())
        contributions = []
        for f in self.features:
            alt = x.copy()
            alt[f] = self.medians.get(f, 0.0)
            delta = score - self._predict(alt.to_numpy())
            contributions.append({"feature": f, "phrase": FEATURE_PHRASES.get(f, f), "value": float(x[f]), "contribution": round(float(delta), 4)})
        contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
        return float(score), contributions[:3]

    def _predict(self, x: np.ndarray) -> float:
        return float(self.model.predict_proba(x.reshape(1, -1))[0, 1])


def main() -> None:
    p = argparse.ArgumentParser(description="Train the transferred fraud risk model on the IEEE-CIS competition and calibrate its threshold on the bank window")
    p.add_argument("--competition", default="data/kaggle")
    p.add_argument("--lakehouse", default=None)
    p.add_argument("--out", default="reports/ml")
    p.add_argument("--model", default="models/fraud_risk_ieee.joblib")
    p.add_argument("--percentile", type=float, default=DEFAULT_PERCENTILE)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--tracking-uri", default=None, help="MLflow store; default MLFLOW_TRACKING_URI, else sqlite:///mlflow.db")
    a = p.parse_args()
    Path(a.model).parent.mkdir(parents=True, exist_ok=True)
    r = train(a.competition, a.out, a.model, lakehouse=a.lakehouse, percentile=a.percentile, limit=a.limit, tracking_uri=a.tracking_uri)
    t = r["model"]["test"] or {}
    print(f"holdout ROC AUC {t.get('roc_auc')}, PR AUC {t.get('pr_auc')}; threshold {r['threshold']:.4f} ({r['threshold_kind']}); fraud_score used: no")
    print(f"mlflow run {r['mlflow']['run_id']} in {r['mlflow']['tracking_uri']} (experiment {r['mlflow']['experiment']})")


if __name__ == "__main__":
    main()
