"""
Dispute intake API: customer chat endpoints and the English HITL console (agent role).

customer_id always comes from the verified session token, never from the body. Console endpoints need
app_role == "agent" (SEC-01). The local test issuer only exists outside production (APP_ENV development
or test); Supabase Auth replaces it (docs/SUPABASE_VERCEL.md section 3).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.auth.session import (
    VerifiedSession,
    create_test_session,
    get_current_session,
    require_agent,
)
from src.core.config import settings
from src.llm.budget import LlmBudget
from src.ops.store import OpsStore
from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.tools.gateway import (
    ActionVerificationError,
    BankingToolGateway,
    RecordNotFoundError,
    UnauthorizedAccessError,
)
from src.understand.jev_extractor import JevExtractor
from src.understand.router import UnderstandRouter

router = APIRouter(prefix="/api/v1")


def load_scorer(model_path: Path):
    """The transferred model (bundle with a contract version, src.ml.fraud_risk_transfer) or the legacy one; None when no file."""
    if not model_path.exists():
        return None
    import joblib

    if "contract_version" in joblib.load(model_path):
        from src.ml.fraud_risk_transfer import TransferRiskScorer

        return TransferRiskScorer(model_path)
    from src.ml.fraud_risk import RiskScorer

    return RiskScorer(model_path)


@lru_cache(maxsize=1)
def get_orchestrator() -> DisputeOrchestrator:
    """One orchestrator per process. Paths come from the environment so tests and deployments can point elsewhere."""
    database_url = os.getenv("DATABASE_URL")
    scorer = load_scorer(Path(os.getenv("FRAUD_MODEL_PATH", "models/fraud_risk_ieee.joblib")))
    if database_url:  # Supabase or a local Postgres: bank serving copy plus the ops schema (migrations applied)
        from src.tools.gateway_postgres import PostgresBankingGateway

        ops = OpsStore(database_url)
        orchestrator = DisputeOrchestrator(gateway=PostgresBankingGateway(database_url), ops=ops, risk_scorer=scorer,
                                           router=UnderstandRouter(jev=JevExtractor(), budget=LlmBudget(ops)))
    else:
        lakehouse = Path(os.getenv("LAKEHOUSE_PATH", "data/lakehouse.duckdb"))
        ops = OpsStore(os.getenv("OPS_DB_PATH", "data/ops.duckdb"))
        orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path=str(lakehouse)), ops=ops, risk_scorer=scorer,
                                           router=UnderstandRouter(jev=JevExtractor(), budget=LlmBudget(ops)))
    orchestrator.ops.seed_questions()  # open questions for the team, answered in the console
    return orchestrator


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")


# ------------------------------------------------------------------ local issuer
class TestSessionRequest(BaseModel):
    customer_id: str = Field(min_length=3, max_length=64)
    app_role: str = Field(default="customer", pattern="^(customer|agent)$")
    ttl_seconds: int = Field(default=3600, ge=60, le=86400)


@router.get("/auth/personas")
def list_personas(orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    """Demo login helper: a few customer ids (segment and country only). Disabled in production."""
    _ensure_local_issuer()
    return orchestrator.gateway.sample_customers()


@router.post("/auth/test-session")
def issue_test_session(payload: TestSessionRequest, orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    """Local issuer for test personas (replaced by Supabase Auth). Facts come from the system of record, never from the body."""
    _ensure_local_issuer()
    identity = orchestrator.gateway.get_customer_identity(payload.customer_id)
    if payload.app_role == "agent":
        token = create_test_session(customer_id=payload.customer_id, name="HITL Agent", country="", segment="",
                                    ttl_seconds=payload.ttl_seconds, app_role="agent")
        return {"token": token, "app_role": "agent", "customer_id": payload.customer_id}
    if identity is None:
        raise _not_found()
    token = create_test_session(customer_id=identity["customer_id"], name=str(identity["name"]), country=str(identity["country"]),
                                segment=str(identity["segment"]), ttl_seconds=payload.ttl_seconds, app_role="customer")
    return {"token": token, "app_role": "customer", "customer_id": identity["customer_id"], "segment": identity["segment"],
            "country": identity["country"]}


def _ensure_local_issuer() -> None:
    if settings.app_env not in ("development", "test"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")


# ----------------------------------------------------------------- customer chat
class StartConversationRequest(BaseModel):
    language: str = Field(default="es", pattern="^(es|pt)$")


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/disputes/conversations", status_code=status.HTTP_201_CREATED)
def start_conversation(payload: StartConversationRequest, session: VerifiedSession = Depends(get_current_session),
                       orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    return orchestrator.start_conversation(session, language=payload.language)


@router.get("/disputes/conversations/{conversation_id}")
def get_conversation(conversation_id: str, session: VerifiedSession = Depends(get_current_session),
                     orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    try:
        return orchestrator.get_conversation(session, conversation_id)
    except UnauthorizedAccessError:
        raise _not_found()


@router.post("/disputes/conversations/{conversation_id}/messages")
def post_message(conversation_id: str, payload: MessageRequest, session: VerifiedSession = Depends(get_current_session),
                 orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    try:
        return orchestrator.handle_message(session, conversation_id, payload.text).as_dict()
    except UnauthorizedAccessError:
        raise _not_found()
    except RecordNotFoundError:
        raise _not_found()
    except ActionVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Action pending, not confirmed: {exc}")


# ------------------------------------------------------------------- HITL console
class CreditDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")


@router.get("/console/cases")
def console_cases(credit_candidates: bool = False, agent: VerifiedSession = Depends(require_agent),
                  orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    return orchestrator.ops.list_cases(only_credit_candidates=credit_candidates)


@router.post("/console/cases/{case_id}/credit-decision")
def console_credit_decision(case_id: str, payload: CreditDecisionRequest, agent: VerifiedSession = Depends(require_agent),
                            orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    """A human approves or rejects the simulated provisional-credit candidate (rule 8). No money moves."""
    case = orchestrator.ops.get_case(case_id)
    if case is None or not case["provisional_credit_candidate"]:
        raise _not_found()
    updated = orchestrator.ops.decide_credit(case_id, payload.decision, decided_by=agent.actor_id)
    orchestrator.ops.audit(conversation_id=case["conversation_id"], customer_id=case["customer_id"], actor=f"agent:{agent.actor_id}",
                           action="CREDIT_CANDIDATE_DECISION", details={"case_id": case_id, "decision": payload.decision,
                                                                        "required_authentication": "AGENT_ROLE"}, verified=True)
    return updated


@router.get("/console/handoffs")
def console_handoffs(status_filter: str | None = None, agent: VerifiedSession = Depends(require_agent),
                     orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    return orchestrator.ops.list_handoffs(status=status_filter)


@router.post("/console/handoffs/{handoff_id}/resolve")
def console_resolve_handoff(handoff_id: str, agent: VerifiedSession = Depends(require_agent),
                            orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    if orchestrator.ops.get_handoff(handoff_id) is None:
        raise _not_found()
    row = orchestrator.ops.resolve_handoff(handoff_id, resolved_by=agent.actor_id)
    orchestrator.ops.audit(conversation_id=row["conversation_id"], customer_id=row["customer_id"], actor=f"agent:{agent.actor_id}",
                           action="HANDOFF_RESOLVED", details={"handoff_id": handoff_id}, verified=True)
    return row


@router.get("/console/locks")
def console_locks(agent: VerifiedSession = Depends(require_agent), orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    return orchestrator.ops.list_locks()


@router.get("/console/audit")
def console_audit(conversation_id: str | None = None, limit: int = 200, agent: VerifiedSession = Depends(require_agent),
                  orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    return orchestrator.ops.list_audit(conversation_id=conversation_id, limit=min(limit, 1000))


# ------------------------------------------------------------- team questions
class QuestionAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)


class NewQuestionRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=120)
    question: str = Field(min_length=5, max_length=2000)
    context: str = Field(default="", max_length=4000)
    options: list[str] = Field(default_factory=list)
    recommendation: str | None = Field(default=None, max_length=1000)
    source: str | None = Field(default=None, max_length=200)


@router.get("/console/questions")
def console_questions(status_filter: str | None = None, agent: VerifiedSession = Depends(require_agent),
                      orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> list[dict[str, Any]]:
    """Open questions the build needs the team to answer; filed here instead of blocking the work."""
    return orchestrator.ops.list_questions(status=status_filter)


@router.post("/console/questions", status_code=status.HTTP_201_CREATED)
def console_new_question(payload: NewQuestionRequest, agent: VerifiedSession = Depends(require_agent),
                         orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    qid = orchestrator.ops.insert_question(topic=payload.topic, question=payload.question, context=payload.context,
                                           options=payload.options, recommendation=payload.recommendation, source=payload.source)
    orchestrator.ops.audit(conversation_id=None, customer_id=None, actor=f"agent:{agent.actor_id}", action="TEAM_QUESTION_FILED",
                           details={"question_id": qid, "topic": payload.topic})
    return orchestrator.ops.get_question(qid)


@router.post("/console/questions/{question_id}/answer")
def console_answer_question(question_id: str, payload: QuestionAnswerRequest, agent: VerifiedSession = Depends(require_agent),
                            orchestrator: DisputeOrchestrator = Depends(get_orchestrator)) -> dict[str, Any]:
    if orchestrator.ops.get_question(question_id) is None:
        raise _not_found()
    row = orchestrator.ops.answer_question(question_id, payload.answer, answered_by=agent.actor_id)
    orchestrator.ops.audit(conversation_id=None, customer_id=None, actor=f"agent:{agent.actor_id}", action="TEAM_QUESTION_ANSWERED",
                           details={"question_id": question_id}, verified=True)
    return row
