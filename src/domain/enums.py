from enum import Enum

class ChannelType(str, Enum):
    CHAT = "chat"
    EMAIL = "email"
    SMS = "sms"
    VOICE_TRANSCRIPT = "voice_transcript"

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class TriageRouting(str, Enum):
    DETERMINISTIC_FASTPATH = "DETERMINISTIC_FASTPATH"  # < 5ms, rule-based execution
    ML_SCORING = "ML_SCORING"                          # Tabular feature risk classification
    AGENTIC_WORKFLOW = "AGENTIC_WORKFLOW"              # LLM reasoning with tool calling
    HITL_ESCALATION = "HITL_ESCALATION"                # Human-in-the-loop triage queue

class ActionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"
    REJECTED = "REJECTED"
    FALLBACK_TRIGGERED = "FALLBACK_TRIGGERED"
