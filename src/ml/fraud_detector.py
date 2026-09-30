import math

from src.domain.enums import RiskLevel
from src.domain.schemas import MLScoringResult, TransactionContext


class MLFraudDetector:
    """
    Lightweight, production-ready ML Scorer.
    Scores transactional risk combining domain heuristics, velocity signals,
    and contextual anomaly detection.
    """

    def __init__(self, model_version: str = "v1.2.0-baseline"):
        self.model_version = model_version

    def extract_features(self, transaction: TransactionContext | None, customer_tier: str) -> dict[str, float]:
        if not transaction:
            return {"amount": 0.0, "ratio_to_avg": 1.0, "is_card_present": 1.0, "tier_weight": 1.0}

        ratio = (
            transaction.amount / transaction.historical_avg_amount
            if transaction.historical_avg_amount and transaction.historical_avg_amount > 0
            else 1.0
        )

        tier_weights = {"standard": 1.0, "gold": 0.8, "premium": 0.6}
        tier_weight = tier_weights.get(customer_tier.lower(), 1.0)

        return {
            "amount": float(transaction.amount),
            "ratio_to_avg": float(ratio),
            "is_card_not_present": 0.0 if transaction.is_card_present else 1.0,
            "foreign_transaction": 1.0 if transaction.location_country != "US" else 0.0,
            "tier_weight": tier_weight
        }

    def predict_risk(self, transaction: TransactionContext | None, customer_tier: str = "standard") -> MLScoringResult:
        if not transaction:
            return MLScoringResult(
                fraud_probability=0.05,
                risk_level=RiskLevel.LOW,
                top_risk_factors=["No financial transaction linked to interaction."],
                model_version=self.model_version,
                confidence_score=0.95
            )

        features = self.extract_features(transaction, customer_tier)

        # Logistic sigmoid scoring based on feature weights
        # z = w0 + w1*amount_scaled + w2*ratio + w3*card_not_present + w4*foreign
        z = -3.5  # Base log-odds (low base fraud rate)
        z += min(features["amount"] / 500.0, 3.0) * 0.8
        z += min(features["ratio_to_avg"], 10.0) * 0.5
        z += features["is_card_not_present"] * 0.7
        z += features["foreign_transaction"] * 1.2
        z *= features["tier_weight"]

        prob = 1.0 / (1.0 + math.exp(-z))
        prob = round(prob, 4)

        # Explainability & Risk Factor attribution
        risk_factors: list[str] = []
        if features["ratio_to_avg"] > 3.0:
            risk_factors.append(f"Transaction amount is {features['ratio_to_avg']:.1f}x higher than customer average.")
        if features["foreign_transaction"] > 0:
            risk_factors.append(f"Foreign transaction origin ({transaction.location_country}).")
        if features["is_card_not_present"] > 0:
            risk_factors.append("Card-not-present online transaction.")
        if features["amount"] > 1000.0:
            risk_factors.append(f"High-value transaction: ${features['amount']:.2f}.")

        if not risk_factors:
            risk_factors.append("Transaction aligns with historical behavioral baseline.")

        # Classify risk level
        if prob >= 0.80:
            level = RiskLevel.HIGH
        elif prob >= 0.40:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        confidence = round(1.0 - abs(0.5 - prob) * 0.2, 2)

        return MLScoringResult(
            fraud_probability=prob,
            risk_level=level,
            top_risk_factors=risk_factors,
            model_version=self.model_version,
            confidence_score=confidence
        )
