from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.agents.orchestrator import HybridOrchestrator
from src.api.dispute_routes import router as dispute_router
from src.auth.session import check_production_identity, local_issuer_enabled
from src.core.config import settings
from src.domain.schemas import (
    CustomerInteractionInput,
    HITLTicket,
    SanitizedInteraction,
    TriageDecision,
)
from src.hitl.queue import hitl_queue
from src.privacy.pii_masker import PIIMasker

local_issuer_enabled()  # SEC-03: raises at import, so the app refuses to start, when LOCAL_ISSUER_ENABLED=true meets APP_ENV=production
check_production_identity()  # and when production has no SUPABASE_URL to verify tokens against

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Production-Ready Hybrid AI & Data System for Customer Interaction Triage and Fraud Prevention."
)

orchestrator = HybridOrchestrator()
app.include_router(dispute_router)

class ResolveTicketRequest(BaseModel):
    ticket_id: str
    human_notes: str


def starter_routes_enabled() -> None:
    """The starter pipeline is the reference baseline: measured in the harness, never deployed (decided 26-Sep). Its routes
    authenticate nothing and take customer_id from the body, so they exist only in development and test."""
    if settings.app_env not in ("development", "test"):
        raise HTTPException(status_code=404, detail="Resource not found.")

STARTER_ONLY = [Depends(starter_routes_enabled)]

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.app_env
    }

@app.post("/api/v1/sanitize", response_model=SanitizedInteraction, dependencies=STARTER_ONLY)
def sanitize_interaction(payload: dict[str, str]):
    text = payload.get("text", "")
    if not text:
        raise HTTPException(status_code=400, detail="Field 'text' is required.")
    return PIIMasker.sanitize(text)

@app.post("/api/v1/triage", response_model=TriageDecision, dependencies=STARTER_ONLY)
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

@app.get("/api/v1/hitl/queue", response_model=list[HITLTicket], dependencies=STARTER_ONLY)
def get_hitl_queue():
    """Retrieve all pending tickets for human review sorted by risk severity."""
    return hitl_queue.get_pending_tickets()

@app.post("/api/v1/hitl/resolve", dependencies=STARTER_ONLY)
def resolve_hitl_ticket(payload: ResolveTicketRequest):
    """Human analyst resolves an escalated ticket."""
    ticket = hitl_queue.resolve_ticket(payload.ticket_id, payload.human_notes)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return {"status": "resolved", "ticket": ticket}


# The React build (frontend/dist) is served by the same app when present, so one domain serves API and UI.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
