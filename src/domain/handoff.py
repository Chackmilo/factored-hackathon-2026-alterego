"""
Structured HITL Handoff Packet Contract.
Ensures human operators receive verified facts, applicable policy clauses,
and actions taken, rather than an unverified text dump.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class TriggeringTransaction(BaseModel):
    transaction_id: str
    amount_original: float
    currency: str
    amount_usd: float
    merchant_name: str
    transaction_date: str

class StructuredHandoffPacket(BaseModel):
    handoff_id: str
    customer_id: str
    customer_name: str
    segment: str
    country: str
    escalation_reason: str
    triggering_transaction: Optional[TriggeringTransaction] = None
    verified_facts: List[str] = Field(default_factory=list)
    actions_taken_automatically: List[str] = Field(default_factory=list)
    applicable_policy_clauses: List[str] = Field(default_factory=list)
    unresolved_questions_for_customer: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
