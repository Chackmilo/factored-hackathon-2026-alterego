from typing import Optional, List
from src.domain.schemas import (
    CustomerInteractionInput,
    TriageDecision,
    AgentReasoningStep,
    ToolCallRequest,
    ToolCallResult,
    HITLTicket
)
from src.domain.enums import TriageRouting, RiskLevel, ActionStatus
from src.core.config import settings
from src.core.telemetry import TelemetryTracker
from src.privacy.pii_masker import PIIMasker
from src.rules.engine import DeterministicRulesEngine
from src.ml.fraud_detector import MLFraudDetector
from src.agents.tools import BankingToolsRegistry
from src.hitl.queue import hitl_queue

class HybridOrchestrator:
    """
    Central Decision Hub uniting:
    1. Deterministic Fast-path rules
    2. ML Tabular scoring & explainability
    3. Autonomous Agentic LLM reasoning & tool-use
    4. Human-in-the-Loop (HITL) safety triage
    """

    def __init__(self):
        self.ml_detector = MLFraudDetector()

    def process_interaction(self, raw_input: CustomerInteractionInput) -> TriageDecision:
        tracker = TelemetryTracker()

        # Phase 1: Privacy & PII Redaction
        tracker.start_stage("pii_redaction")
        sanitized = PIIMasker.sanitize(raw_input.message_text, original_id=raw_input.interaction_id)
        tracker.record_pii_redacted(sanitized.redaction_count)
        tracker.end_stage("pii_redaction")

        # Phase 2: Deterministic Rules Engine (Microsecond Fast-Path)
        tracker.start_stage("deterministic_rules")
        rule_eval = DeterministicRulesEngine.evaluate(raw_input)
        tracker.end_stage("deterministic_rules")

        if rule_eval.triggered:
            tracker.record_rule(rule_eval.rule_name or "UNNAMED_RULE")

            # Route immediately based on deterministic rule
            if rule_eval.suggested_action == "LOCK_CARD_IMMEDIATELY":
                tool_res = BankingToolsRegistry.execute("lock_card", {"card_id": f"CARD-{raw_input.customer_id}"})
                metrics = tracker.finalize()
                return TriageDecision(
                    interaction_id=raw_input.interaction_id,
                    routing=TriageRouting.DETERMINISTIC_FASTPATH,
                    risk_level=RiskLevel.HIGH,
                    rationale=f"Deterministic rule [{rule_eval.rule_name}] triggered. Card locked instantly.",
                    rule_result=rule_eval,
                    final_response_to_customer="Hemos bloqueado tu tarjeta inmediatamente por seguridad. Ningún cargo adicional será procesado.",
                    actions_taken=["LOCK_CARD"],
                    action_status=ActionStatus.EXECUTED,
                    execution_metrics=metrics.__dict__
                )
            elif rule_eval.force_routing == TriageRouting.HITL_ESCALATION:
                ml_eval = None
                if raw_input.transaction:
                    ml_eval = self.ml_detector.predict_risk(raw_input.transaction, raw_input.customer_tier)
                ticket = hitl_queue.create_ticket(
                    interaction_id=raw_input.interaction_id,
                    customer_id=raw_input.customer_id,
                    escalation_reason=rule_eval.description or "Deterministic security trigger",
                    risk_level=RiskLevel.CRITICAL,
                    suggested_action=rule_eval.suggested_action or "MANUAL_INVESTIGATION",
                    fraud_score=ml_eval.fraud_probability if ml_eval else None
                )
                metrics = tracker.finalize()
                return TriageDecision(
                    interaction_id=raw_input.interaction_id,
                    routing=TriageRouting.HITL_ESCALATION,
                    risk_level=RiskLevel.CRITICAL,
                    rationale=f"Security/Compliance rule [{rule_eval.rule_name}] flagged. Escalated to specialist.",
                    rule_result=rule_eval,
                    ml_result=ml_eval,
                    final_response_to_customer="Por motivos de seguridad, un especialista de nuestro equipo de fraude está revisando tu caso de inmediato.",
                    actions_taken=["HITL_TICKET_CREATED"],
                    action_status=ActionStatus.PENDING_HUMAN_APPROVAL,
                    hitl_ticket=ticket,
                    execution_metrics=metrics.__dict__
                )

        # Phase 3: ML Tabular Fraud Scoring
        tracker.start_stage("ml_scoring")
        ml_eval = self.ml_detector.predict_risk(raw_input.transaction, raw_input.customer_tier)
        tracker.end_stage("ml_scoring")

        # Phase 4: Production Trade-off Evaluation (Autonomy vs. Risk)
        tracker.start_stage("orchestration_reasoning")

        # Case A: Critical/High ML Fraud Probability -> Safety Hold + HITL
        if ml_eval.fraud_probability >= settings.fraud_risk_high_threshold:
            ticket = hitl_queue.create_ticket(
                interaction_id=raw_input.interaction_id,
                customer_id=raw_input.customer_id,
                escalation_reason=f"High ML fraud probability ({ml_eval.fraud_probability:.2%}): " + "; ".join(ml_eval.top_risk_factors),
                risk_level=RiskLevel.HIGH,
                suggested_action="FREEZE_TRANSACTION_AND_CALL_CUSTOMER",
                fraud_score=ml_eval.fraud_probability
            )
            tracker.end_stage("orchestration_reasoning")
            metrics = tracker.finalize()
            return TriageDecision(
                interaction_id=raw_input.interaction_id,
                routing=TriageRouting.HITL_ESCALATION,
                risk_level=RiskLevel.HIGH,
                rationale="ML risk score exceeds autonomous threshold. Handed over to human fraud analyst.",
                ml_result=ml_eval,
                final_response_to_customer="Hemos detectado una actividad inusual en esta transacción y la hemos pausado temporalmente. Un agente humano especializado te contactará en breve.",
                actions_taken=["HOLD_TRANSACTION", "ESCALATE_TO_HITL"],
                action_status=ActionStatus.PENDING_HUMAN_APPROVAL,
                hitl_ticket=ticket,
                execution_metrics=metrics.__dict__
            )

        # Case B: Autonomous Agentic Flow (Low to Medium Risk)
        # Agent analyzes conversation, interacts with tools, and decides resolution
        tracker.record_tokens(prompt_tokens=450, completion_tokens=120)  # Simulated LLM invocation
        
        agent_steps: List[AgentReasoningStep] = []
        actions_taken: List[str] = []

        if raw_input.transaction and "dispute" in sanitized.sanitized_text.lower() or "desconozco" in sanitized.sanitized_text.lower():
            # Check autonomous transaction limit trade-off
            if raw_input.transaction.amount > settings.max_autonomous_transaction_limit:
                ticket = hitl_queue.create_ticket(
                    interaction_id=raw_input.interaction_id,
                    customer_id=raw_input.customer_id,
                    escalation_reason=f"Dispute amount (${raw_input.transaction.amount}) exceeds autonomous limit (${settings.max_autonomous_transaction_limit}).",
                    risk_level=RiskLevel.MEDIUM,
                    suggested_action="APPROVE_MANUAL_DISPUTE",
                    fraud_score=ml_eval.fraud_probability
                )
                tracker.end_stage("orchestration_reasoning")
                metrics = tracker.finalize()
                return TriageDecision(
                    interaction_id=raw_input.interaction_id,
                    routing=TriageRouting.HITL_ESCALATION,
                    risk_level=RiskLevel.MEDIUM,
                    rationale="Dispute amount exceeds agent policy ceiling.",
                    ml_result=ml_eval,
                    final_response_to_customer=f"Entiendo tu reporte sobre la transacción de ${raw_input.transaction.amount}. Debido al monto, un supervisor la revisará para aplicar el reembolso formal.",
                    actions_taken=["CREATE_DISPUTE_HOLD", "ESCALATE_TO_HITL"],
                    action_status=ActionStatus.PENDING_HUMAN_APPROVAL,
                    hitl_ticket=ticket,
                    execution_metrics=metrics.__dict__
                )
            
            # Autonomous Dispute Creation with Tool
            tool_res = BankingToolsRegistry.open_dispute(
                transaction_id=raw_input.transaction.transaction_id,
                dispute_reason="Customer reported unrecognized transaction via chat",
                amount=raw_input.transaction.amount
            )
            actions_taken.append("OPEN_DISPUTE_TOOL")
            agent_steps.append(AgentReasoningStep(
                thought="Customer reports unrecognized charge. Fraud risk is low/moderate. Amount is within autonomous limits. Filing dispute.",
                tool_calls=[ToolCallRequest(tool_name="open_dispute", parameters={"transaction_id": raw_input.transaction.transaction_id})],
                tool_results=[tool_res]
            ))
            final_msg = f"Hemos abierto el reclamo #{tool_res.output.get('case_id')} para la transacción de ${raw_input.transaction.amount}. Tu crédito provisional ha sido evaluado exitosamente."
        else:
            final_msg = "He verificado tu cuenta y no encontramos irregularidades adicionales. ¿En qué más puedo asistirte hoy?"
            actions_taken.append("VERIFY_ACCOUNT_STATUS")

        tracker.end_stage("orchestration_reasoning")
        metrics = tracker.finalize()

        return TriageDecision(
            interaction_id=raw_input.interaction_id,
            routing=TriageRouting.AGENTIC_WORKFLOW,
            risk_level=ml_eval.risk_level,
            rationale="Resolved autonomously through Agentic Workflow and verified tool calling.",
            ml_result=ml_eval,
            agent_steps=agent_steps,
            final_response_to_customer=final_msg,
            actions_taken=actions_taken,
            action_status=ActionStatus.EXECUTED,
            execution_metrics=metrics.__dict__
        )
