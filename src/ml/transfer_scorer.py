"""
Serving side of the fraud risk score transferred from IEEE-CIS: the API loads it when models/fraud_risk_ieee.joblib exists.

Training lives in src.ml.fraud_risk_transfer, which this module never imports, so serving needs none of the training
tools (MLflow and the rest of the dev group stay out of the runtime install; tests/test_runtime_dependencies.py).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.ml.bank_adapter import rows_to_canonical
from src.ml.feature_contract import FEATURE_PHRASES, build_contract_features


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
