"""
Structured HITL Handoff Packet Contract.
Ensures human operators receive verified facts, applicable policy clauses,
and actions taken, rather than an unverified text dump.
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TriggeringTransaction(BaseModel):
    transaction_id: str
    amount_original: float
    currency: str
    amount_usd: float | None  # None when the system of record has no USD value (DATA_GAP_AMOUNT_USD)
    merchant_name: str | None = None
    transaction_date: str

class StructuredHandoffPacket(BaseModel):
    handoff_id: str
    customer_id: str
    customer_name: str
    segment: str
    country: str
    escalation_reason: str
    customer_request: str = ""  # the customer's own words after PII masking
    triggering_transaction: TriggeringTransaction | None = None
    verified_facts: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    actions_taken_automatically: list[str] = Field(default_factory=list)
    applicable_policy_clauses: list[str] = Field(default_factory=list)
    secondary_clauses: list[str] = Field(default_factory=list)
    provisional_credit_recommendation: dict[str, Any] | None = None  # {"amount_usd": ..., "clause": "POL-AUT-150"} or None
    risk_explanation: dict[str, Any] | None = None  # {"score": ..., "top_features": [...]} when a model scored the charge
    case_memory: dict[str, Any] = Field(default_factory=dict)
    card_lock: dict[str, Any] | None = None  # {"recommended": bool, "reason": ..., "status": offered|locked|refused}
    unresolved_questions_for_customer: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
