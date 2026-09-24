import uuid
from typing import List, Dict, Optional
from datetime import datetime
from src.domain.schemas import HITLTicket
from src.domain.enums import RiskLevel

class HITLQueueManager:
    """
    In-memory / Persistent Human-in-the-Loop review queue.
    Orders tickets by risk severity and SLA criticality.
    """

    def __init__(self):
        self._tickets: Dict[str, HITLTicket] = {}

    def create_ticket(
        self,
        interaction_id: str,
        customer_id: str,
        escalation_reason: str,
        risk_level: RiskLevel,
        suggested_action: str,
        fraud_score: Optional[float] = None
    ) -> HITLTicket:
        ticket_id = f"TICKET-{uuid.uuid4().hex[:8].upper()}"
        ticket = HITLTicket(
            ticket_id=ticket_id,
            interaction_id=interaction_id,
            customer_id=customer_id,
            escalation_reason=escalation_reason,
            risk_level=risk_level,
            fraud_score=fraud_score,
            suggested_action=suggested_action,
            created_at=datetime.utcnow(),
            resolved=False
        )
        self._tickets[ticket_id] = ticket
        return ticket

    def get_pending_tickets(self) -> List[HITLTicket]:
        # Sort pending by risk priority: CRITICAL > HIGH > MEDIUM > LOW
        priority_map = {RiskLevel.CRITICAL: 0, RiskLevel.HIGH: 1, RiskLevel.MEDIUM: 2, RiskLevel.LOW: 3}
        pending = [t for t in self._tickets.values() if not t.resolved]
        return sorted(pending, key=lambda t: priority_map.get(t.risk_level, 99))

    def resolve_ticket(self, ticket_id: str, human_notes: str) -> Optional[HITLTicket]:
        ticket = self._tickets.get(ticket_id)
        if ticket:
            ticket.resolved = True
            ticket.human_notes = human_notes
        return ticket

# Singleton instance
hitl_queue = HITLQueueManager()
