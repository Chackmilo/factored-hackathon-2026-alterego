import re
from typing import Optional
from src.domain.schemas import CustomerInteractionInput, RuleEvaluationResult
from src.domain.enums import TriageRouting, RiskLevel

class DeterministicRulesEngine:
    """
    Evaluates hard deterministic business & security rules in < 2ms.
    Bypasses LLM when deterministic logic is strictly superior, safer, and cheaper.
    """

    CRITICAL_INTENT_KEYWORDS = [
        r"\b(lock|freeze|block|desactivar|bloquear)\s+(my\s+)?(card|tarjeta|account|cuenta)\b",
        r"\b(stolen|robada|robado|lost|extraviada)\s+(card|tarjeta|phone)\b",
        r"\b(unauthorized charge|cargo no reconocido|fraude total)\b"
    ]

    SANCTIONED_COUNTRIES = {"NK", "IR", "SY"}

    PROMPT_INJECTION_PATTERNS = [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"system\s*prompt",
        r"act\s+as\s+an\s+unrestricted",
        r"you\s+are\s+now\s+in\s+developer\s+mode"
    ]

    @classmethod
    def evaluate(cls, interaction: CustomerInteractionInput) -> RuleEvaluationResult:
        text = interaction.message_text.lower()

        # Rule 1: Security & Guardrail Check (Prompt Injection Detection)
        for pattern in cls.PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, text):
                return RuleEvaluationResult(
                    triggered=True,
                    rule_name="SECURITY_PROMPT_INJECTION_ATTEMPT",
                    description="Detected adversarial prompt injection attempt.",
                    force_routing=TriageRouting.HITL_ESCALATION,
                    suggested_action="FLAG_FOR_SECURITY_AUDIT"
                )

        # Rule 2: Country Sanction / Compliance Rule
        if interaction.transaction and interaction.transaction.location_country in cls.SANCTIONED_COUNTRIES:
            return RuleEvaluationResult(
                triggered=True,
                rule_name="COMPLIANCE_SANCTIONED_GEO_BLOCK",
                description=f"Transaction originated from sanctioned jurisdiction: {interaction.transaction.location_country}",
                force_routing=TriageRouting.DETERMINISTIC_FASTPATH,
                suggested_action="HARD_DECLINE_AND_FREEZE"
            )

        # Rule 3: High-Value Immediate Anomaly Rule (>10x historical average)
        if interaction.transaction and interaction.transaction.historical_avg_amount:
            ratio = interaction.transaction.amount / interaction.transaction.historical_avg_amount
            if ratio >= 10.0 and interaction.transaction.amount > 1000.0:
                return RuleEvaluationResult(
                    triggered=True,
                    rule_name="HIGH_VELOCITY_ANOMALY_SPIKE",
                    description=f"Transaction amount (${interaction.transaction.amount}) is {ratio:.1f}x higher than historical baseline.",
                    force_routing=TriageRouting.HITL_ESCALATION,
                    suggested_action="TEMPORARY_HOLD_CONFIRM_WITH_CUSTOMER"
                )

        # Rule 4: Explicit Immediate Action Command ("Lock Card", "Tarjeta Robada")
        for pattern in cls.CRITICAL_INTENT_KEYWORDS:
            if re.search(pattern, text):
                return RuleEvaluationResult(
                    triggered=True,
                    rule_name="IMMEDIATE_CARD_LOCK_REQUEST",
                    description="Customer explicitly commanded immediate emergency card/account lock.",
                    force_routing=TriageRouting.DETERMINISTIC_FASTPATH,
                    suggested_action="LOCK_CARD_IMMEDIATELY"
                )

        return RuleEvaluationResult(triggered=False)
