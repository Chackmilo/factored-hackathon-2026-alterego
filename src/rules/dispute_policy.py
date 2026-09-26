"""
Synthetic Dispute Policy Engine for OmniGuard AI.
Implements the definitive rules from Section 2 / Decision 4 of the Team Brief.

Rule Clauses:
- POL-WIN-60: Transaction date must be <= 60 calendar days from current process date.
- POL-AUT-150: Autonomous simulated provisional credit for <= $150 USD for mature Premium/Plus customers with 0 recent complaints.
- POL-AUT-INTAKE: Autonomous intake case creation (status = INTAKE_RECEIVED).
- POL-ESC-500: Mandatory HITL escalation if claimed amount > $500 USD.
- POL-ESC-ML-RISK: Mandatory HITL escalation if ML fraud risk score > 0.70.
- POL-ESC-MULTI: Mandatory HITL escalation if > 2 charges disputed within 48h.
- POL-ESC-LEGAL: Mandatory HITL escalation if customer cites regulators (CONDUSEF, SFC, BCRA, PROCON) or legal action.
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Optional
import re

@dataclass
class DisputePolicyInput:
    customer_id: str
    customer_segment: str  # 'Premium', 'Plus', 'Basic', 'Student'
    customer_country: str  # 'Colombia', 'México', 'Argentina'
    account_age_days: int
    complaints_last_90d: int
    transaction_id: str
    transaction_date: datetime
    transaction_amount: float
    transaction_currency: str
    amount_usd: float
    ml_risk_score: float = 0.0
    recent_disputed_charges_count: int = 1
    customer_message: str = ""
    current_date: date = date(2026, 6, 17)  # Dataset reference anchor date

@dataclass
class DisputePolicyDecision:
    is_eligible: bool
    policy_outcome: str  # "AUTONOMOUS_RESOLUTION", "SAFE_POLICY_ABSTENTION", "MANDATORY_HITL_ESCALATION"
    provisional_credit_eligible: bool
    provisional_credit_amount_usd: float
    cited_clauses: List[str] = field(default_factory=list)
    escalation_reason: Optional[str] = None
    action_required: str = "NONE"  # "OPEN_DISPUTE_AND_CREDIT", "OPEN_DISPUTE_ONLY", "HOLD_CARD_AND_ESCALATE", "ABSTAIN"
    explanation_es: str = ""
    explanation_pt: str = ""

class DisputePolicyEngine:
    """
    Deterministic dispute intake policy evaluator.
    No model hallucinations; rule evaluations produce traceable audit clauses.
    """

    REGULATOR_OR_LEGAL_KEYWORDS = [
        r"\b(condusef|sfc|superintendencia|bcra|procon)\b",
        r"\b(demanda|abogado|tribunal|denuncia\s+penal)\b",
        r"\b(processo|advogado|denúncia)\b",
    ]

    @classmethod
    def evaluate(cls, policy_input: DisputePolicyInput) -> DisputePolicyDecision:
        # Calculate days since transaction relative to current_date
        tx_date = policy_input.transaction_date.date() if isinstance(policy_input.transaction_date, datetime) else policy_input.transaction_date
        days_diff = (policy_input.current_date - tx_date).days

        # 1. FILING WINDOW CHECK (POL-WIN-60)
        if days_diff > 60 or days_diff < 0:
            return DisputePolicyDecision(
                is_eligible=False,
                policy_outcome="SAFE_POLICY_ABSTENTION",
                provisional_credit_eligible=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-WIN-60"],
                escalation_reason="OUT_OF_POLICY_WINDOW",
                action_required="ABSTAIN",
                explanation_es=f"La transacción ocurrió hace {days_diff} días, superando el plazo de 60 días para disputas automáticas. Por favor acérquese a una sucursal.",
                explanation_pt=f"A transação ocorreu há {days_diff} dias, excedendo o prazo de 60 dias para contestações automáticas. Por favor, dirija-se a uma agência."
            )

        # 2. LEGAL / REGULATOR ESCALATION (POL-ESC-LEGAL)
        msg_lower = policy_input.customer_message.lower()
        for pattern in cls.REGULATOR_OR_LEGAL_KEYWORDS:
            if re.search(pattern, msg_lower):
                return DisputePolicyDecision(
                    is_eligible=True,
                    policy_outcome="MANDATORY_HITL_ESCALATION",
                    provisional_credit_eligible=False,
                    provisional_credit_amount_usd=0.0,
                    cited_clauses=["POL-WIN-60", "POL-ESC-LEGAL"],
                    escalation_reason="REGULATOR_OR_LEGAL_CITING",
                    action_required="HOLD_CARD_AND_ESCALATE",
                    explanation_es="Su caso requiere atención prioritaria por parte de un especialista de atención bancaria y cumplimiento.",
                    explanation_pt="Seu caso requer atenção prioritária de um especialista em atendimento bancário e conformidade."
                )

        # 3. HIGH-VALUE ESCALATION (POL-ESC-500)
        if policy_input.amount_usd > 500.0:
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome="MANDATORY_HITL_ESCALATION",
                provisional_credit_eligible=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-WIN-60", "POL-ESC-500"],
                escalation_reason="AMOUNT_EXCEEDS_500_USD",
                action_required="HOLD_CARD_AND_ESCALATE",
                explanation_es=f"El monto disputado (${policy_input.amount_usd:,.2f} USD equiv.) supera el límite de resolución automática ($500 USD). Un especialista revisará el caso.",
                explanation_pt=f"O valor contestado (${policy_input.amount_usd:,.2f} USD equiv.) excede o limite de resolução automática ($500 USD). Um especialista revisará o caso."
            )

        # 4. HIGH ML FRAUD RISK SCORE (POL-ESC-ML-RISK)
        if policy_input.ml_risk_score > 0.70:
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome="MANDATORY_HITL_ESCALATION",
                provisional_credit_eligible=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-WIN-60", "POL-ESC-ML-RISK"],
                escalation_reason="HIGH_FRAUD_RISK_SCORE",
                action_required="HOLD_CARD_AND_ESCALATE",
                explanation_es="Se ha detectado un riesgo elevado de seguridad. Aplicamos bloqueo preventivo y transferimos el caso al equipo de prevención de fraude.",
                explanation_pt="Detectamos um alto risco de segurança. Aplicamos bloqueio preventivo e transferimos o caso para a equipe de prevenção a fraudes."
            )

        # 5. MULTIPLE CHARGES DISPUTED WITHIN 48H (POL-ESC-MULTI)
        if policy_input.recent_disputed_charges_count > 2:
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome="MANDATORY_HITL_ESCALATION",
                provisional_credit_eligible=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-WIN-60", "POL-ESC-MULTI"],
                escalation_reason="MULTIPLE_CHARGES_48H",
                action_required="HOLD_CARD_AND_ESCALATE",
                explanation_es="Se reportaron múltiples cargos no reconocidos en menos de 48 horas. Se activa protocolo de seguridad con escalamiento a especialista.",
                explanation_pt="Foram relatadas múltiplas cobranças não reconhecidas em menos de 48 horas. Protocolo de segurança ativado com transferência para especialista."
            )

        # 6. AUTONOMOUS INTAKE WITH SIMULATED PROVISIONAL CREDIT (POL-AUT-150)
        is_tier_eligible = policy_input.customer_segment in ["Premium", "Plus"]
        is_mature_account = policy_input.account_age_days > 180
        is_clean_history = policy_input.complaints_last_90d == 0
        is_amount_eligible = policy_input.amount_usd <= 150.0

        if is_amount_eligible and is_tier_eligible and is_mature_account and is_clean_history:
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome="AUTONOMOUS_RESOLUTION",
                provisional_credit_eligible=True,
                provisional_credit_amount_usd=policy_input.amount_usd,
                cited_clauses=["POL-WIN-60", "POL-AUT-150"],
                action_required="OPEN_DISPUTE_AND_CREDIT",
                explanation_es=f"Su reclamo por ${policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} ha sido ingresado exitosamente. Se ha aplicado un crédito provisional simulado de ${policy_input.amount_usd:,.2f} USD.",
                explanation_pt=f"Sua contestação de ${policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} foi registrada com sucesso. Um crédito provisório simulado de ${policy_input.amount_usd:,.2f} USD foi aplicado."
            )

        # 7. AUTONOMOUS INTAKE WITHOUT PROVISIONAL CREDIT (POL-AUT-INTAKE)
        return DisputePolicyDecision(
            is_eligible=True,
            policy_outcome="AUTONOMOUS_RESOLUTION",
            provisional_credit_eligible=False,
            provisional_credit_amount_usd=0.0,
            cited_clauses=["POL-WIN-60", "POL-AUT-INTAKE"],
            action_required="OPEN_DISPUTE_ONLY",
            explanation_es=f"Su solicitud de disputa para el cargo de ${policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} ha sido registrada (Ticket INTAKE_RECEIVED). Recibirá respuesta formal en 3 a 5 días hábiles.",
            explanation_pt=f"Sua solicitação de contestação para a cobrança de ${policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} foi registrada (Protocolo INTAKE_RECEIVED). Você receberá resposta formal em 3 a 5 dias úteis."
        )
