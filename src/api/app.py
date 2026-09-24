from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from src.core.config import settings
from src.domain.schemas import (
    CustomerInteractionInput,
    TriageDecision,
    SanitizedInteraction,
    HITLTicket
)
from src.privacy.pii_masker import PIIMasker
from src.agents.orchestrator import HybridOrchestrator
from src.hitl.queue import hitl_queue

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-Ready Hybrid AI & Data System for Customer Interaction Triage and Fraud Prevention."
)

orchestrator = HybridOrchestrator()

class ResolveTicketRequest(BaseModel):
    ticket_id: str
    human_notes: str

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env
    }

@app.post("/api/v1/sanitize", response_model=SanitizedInteraction)
def sanitize_interaction(payload: Dict[str, str]):
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Field 'text' is required.")
    return PIIMasker.sanitize(text)

@app.post("/api/v1/triage", response_model=TriageDecision)
def process_customer_interaction(interaction: CustomerInteractionInput):
    """
    Main triage endpoint combining Deterministic rules, ML risk scoring,
    Agentic tool execution, and Human-in-the-Loop escalation.
    """
    try:
        decision = orchestrator.process_interaction(interaction)
        return decision
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.get("/api/v1/hitl/queue", response_model=List[HITLTicket])
def get_hitl_queue():
    """Retrieve all pending tickets for human review sorted by risk severity."""
    return hitl_queue.get_pending_tickets()

@app.post("/api/v1/hitl/resolve")
def resolve_hitl_ticket(payload: ResolveTicketRequest):
    """Human analyst resolves an escalated ticket."""
    ticket = hitl_queue.resolve_ticket(payload.ticket_id, payload.human_notes)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return {"status": "resolved", "ticket": ticket}
