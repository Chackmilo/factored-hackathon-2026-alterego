"""
Reference baseline: the starter pipeline (HybridOrchestrator) driven through a minimal adapter, measured as is.

It is single-shot and English-keyword based: the first customer message goes in with the first charge as
transaction context. Its mock tools never read back, so every action it reports is unverified; an immediate card
lock and refund wording count as unsafe outcomes (decided 26-Sep).
"""
from __future__ import annotations

import re
import time

from src.agents.orchestrator import HybridOrchestrator
from src.domain.schemas import CustomerInteractionInput, TransactionContext
from src.eval.cases import EvalCase
from src.eval.runner import OUTCOME_ACCEPTED, CaseResult, judge

TIER = {"Premium": "premium", "Plus": "gold", "Basic": "standard", "Student": "standard"}
PT_MARKERS = re.compile(r"\b(não|você|cartão|cobrança|contestação)\b", re.IGNORECASE)


def run_case_baseline(case: EvalCase, orchestrator: HybridOrchestrator | None = None) -> CaseResult:
    orchestrator = orchestrator or HybridOrchestrator()
    result = CaseResult(case_id=case.case_id, system="baseline_starter")
    if case.attack:  # the starter authenticates nothing: /api/v1/triage takes customer_id from the request body
        result.final_outcome, result.turns = OUTCOME_ACCEPTED, 1
        judge(case, result)
        return result
    first_tx = case.transactions[0] if case.transactions else None
    transaction = None
    if first_tx:
        transaction = TransactionContext(
            transaction_id=first_tx["transaction_id"], amount=float(first_tx.get("amount_usd") or first_tx["amount"]) or 0.01,
            currency="USD", merchant_name=str(first_tx.get("merchant_name") or "Unknown"), merchant_category=str(first_tx.get("merchant_category") or "retail"),
            location_country=str(case.customer.get("country", "CO"))[:2].upper(),
        )
    payload = CustomerInteractionInput(interaction_id=case.case_id, customer_id=case.customer_id, message_text=case.messages[0],
                                       customer_tier=TIER.get(str(case.customer.get("segment")), "standard"), transaction=transaction)
    started = time.perf_counter()
    try:
        decision = orchestrator.process_interaction(payload)
        result.latency_ms = (time.perf_counter() - started) * 1000
        result.turns = 1
        result.replies = [decision.final_response_to_customer]
        actions = set(decision.actions_taken)
        result.escalated = decision.routing.value == "HITL_ESCALATION"
        result.case_opened = bool(actions & {"OPEN_DISPUTE_TOOL", "CREATE_DISPUTE_HOLD"})
        result.lock_status = "locked" if "LOCK_CARD" in actions else None
        result.final_outcome = "MANDATORY_HITL_ESCALATION" if result.escalated else "AUTONOMOUS_RESOLUTION"
        result.escalation_reason = decision.rule_result.rule_name if (decision.rule_result and decision.rule_result.triggered) else None
        result.reply_language = "es"  # its templates are Spanish only
        # every reported action comes from an always-succeeding mock with no read-back
        result.unverified_actions = len(actions & {"OPEN_DISPUTE_TOOL", "CREATE_DISPUTE_HOLD", "LOCK_CARD", "HOLD_TRANSACTION"})
    except Exception as exc:
        result.latency_ms = (time.perf_counter() - started) * 1000
        result.error = f"{type(exc).__name__}: {exc}"
    judge(case, result)
    return result
