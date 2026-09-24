from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from src.domain.enums import ChannelType, RiskLevel, TriageRouting, ActionStatus

class TransactionContext(BaseModel):
    transaction_id: str
    amount: float = Field(gt=0, description="Transaction amount in USD")
    currency: str = "USD"
    merchant_name: str
    merchant_category: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    location_country: str = "US"
    is_card_present: bool = False
    historical_avg_amount: Optional[float] = 50.0

class CustomerInteractionInput(BaseModel):
    interaction_id: str
    customer_id: str
    channel: ChannelType = ChannelType.CHAT
    message_text: str = Field(min_length=1, max_length=5000)
    customer_tier: str = "standard"  # standard, gold, premium
    transaction: Optional[TransactionContext] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("message_text")
    @classmethod
    def clean_message(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Message text cannot be empty or just whitespace.")
        return cleaned

class SanitizedInteraction(BaseModel):
    original_id: str
    sanitized_text: str
    detected_pii_types: List[str] = Field(default_factory=list)
    redaction_count: int = 0

class RuleEvaluationResult(BaseModel):
    triggered: bool
    rule_name: Optional[str] = None
    description: Optional[str] = None
    force_routing: Optional[TriageRouting] = None
    suggested_action: Optional[str] = None

class MLScoringResult(BaseModel):
    fraud_probability: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel
    top_risk_factors: List[str] = Field(default_factory=list)
    model_version: str = "xgb_fraud_v1.0"
    confidence_score: float = Field(ge=0.0, le=1.0)

class ToolCallRequest(BaseModel):
    tool_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)

class ToolCallResult(BaseModel):
    tool_name: str
    success: bool
    output: Dict[str, Any]
    error_message: Optional[str] = None

class AgentReasoningStep(BaseModel):
    thought: str
    tool_calls: List[ToolCallRequest] = Field(default_factory=list)
    tool_results: List[ToolCallResult] = Field(default_factory=list)

class HITLTicket(BaseModel):
    ticket_id: str
    interaction_id: str
    customer_id: str
    escalation_reason: str
    risk_level: RiskLevel
    fraud_score: Optional[float] = None
    suggested_action: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False
    human_notes: Optional[str] = None

class TriageDecision(BaseModel):
    interaction_id: str
    routing: TriageRouting
    risk_level: RiskLevel
    rationale: str
    rule_result: Optional[RuleEvaluationResult] = None
    ml_result: Optional[MLScoringResult] = None
    agent_steps: List[AgentReasoningStep] = Field(default_factory=list)
    final_response_to_customer: str
    actions_taken: List[str] = Field(default_factory=list)
    action_status: ActionStatus
    hitl_ticket: Optional[HITLTicket] = None
    execution_metrics: Dict[str, Any] = Field(default_factory=dict)
