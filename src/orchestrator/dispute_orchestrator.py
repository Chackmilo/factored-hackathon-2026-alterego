"""
Deterministic, multi-turn orchestrator for transaction-dispute intake.

Understand (keyword extractor or Jev behind the same contract) -> Decide (DisputePolicyEngine, policy v2.3)
-> Act (ops store for cases, handoffs and locks; the bank gateway for the card lock) -> Verify (read back
before telling the customer) -> Escalate (structured handoff packet). The model never decides or acts:
every branch here is a clause outcome or a customer confirmation. State lives in the ops store, never in memory.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from src.auth.session import VerifiedSession
from src.domain.handoff import StructuredHandoffPacket, TriggeringTransaction
from src.ops.store import OpsStore
from src.privacy.pii_masker import PIIMasker
from src.rag.policy_explainer import PolicyExplainer
from src.rules.dispute_policy import (
    DISPUTABLE_STATUS,
    DISPUTABLE_TYPES,
    OUTCOME_ABSTENTION,
    OUTCOME_AUTONOMOUS,
    OUTCOME_CLARIFICATION,
    OUTCOME_ESCALATION,
    DisputePolicyDecision,
    DisputePolicyEngine,
    DisputePolicyInput,
)
from src.tools.gateway import (
    ActionVerificationError,
    BankingToolGateway,
    RecordNotFoundError,
    SystemOfRecordUnavailableError,
    UnauthorizedAccessError,
)
from src.tools.risk_zone import RiskZoneValidator, RiskZoneVerdict, cross_check
from src.understand.keyword_extractor import KeywordIntentExtractor, UnderstandResult
from src.understand.router import UnderstandRouter
from src.understand.topics import OUT_OF_SCOPE_TOPICS

# The bank did not answer: both gateways raise SystemOfRecordUnavailableError; a proxy or a client library may raise the builtins.
SYSTEM_OF_RECORD_UNAVAILABLE = (SystemOfRecordUnavailableError, TimeoutError, ConnectionError)

TEXT = {
    # TQ-042: the offer is written in the other language, for the customer who may not read the one in use
    "language_offer": {
        "es": ' Se preferir continuar em português, escreva "português".',
        "pt": ' Si prefiere continuar en español, escriba "español".',
    },
    # TQ-044: several topics in one message are taken one by one, the most critical first; the count is never shown
    "several_topics": {
        "es": "Veo que nos escribe por más de un tema. Los atenderemos uno por uno, empezando por el más urgente. ",
        "pt": "Vejo que você nos escreve por mais de um assunto. Vamos atender um de cada vez, começando pelo mais urgente. ",
    },
    "topic_not_related": {
        "es": " Sobre su consulta de {label}: ese tema no corresponde a este canal, que atiende disputas de cargos. Lo atiende la línea de atención o la sección correspondiente de la app.",
        "pt": " Sobre a sua solicitação de {label}: esse assunto não corresponde a este canal, que atende contestações de cobranças. Ele é atendido pela central de atendimento ou pela seção correspondente do aplicativo.",
    },
    "language_set": {
        "es": "Listo, continuamos en español. Puede seguir con su solicitud.",
        "pt": "Pronto, continuamos em português. Pode seguir com a sua solicitação.",
    },
    "lock_offer": {
        "es": " Como reportó que su tarjeta pudo ser robada o extraviada, podemos aplicar un bloqueo temporal a la tarjeta {product}. ¿Desea que la bloqueemos ahora? Responda Sí o No.",
        "pt": " Como você relatou que o cartão pode ter sido roubado ou perdido, podemos aplicar um bloqueio temporário ao cartão {product}. Deseja que bloqueemos agora? Responda Sim ou Não.",
    },
    "lock_first": {
        "es": "Antes de revisar los movimientos, protejamos su tarjeta.",
        "pt": "Antes de revisar os movimentos, vamos proteger seu cartão.",
    },
    "lock_offer_multi": {
        "es": " Por los varios cargos no reconocidos, podemos aplicar un bloqueo temporal a la tarjeta {product}. ¿Desea que la bloqueemos ahora? Responda Sí o No.",
        "pt": " Pelas várias cobranças não reconhecidas, podemos aplicar um bloqueio temporário ao cartão {product}. Deseja que bloqueemos agora? Responda Sim ou Não.",
    },
    "lock_done": {
        "es": "Listo: la tarjeta {product} quedó bloqueada temporalmente (verificado en el sistema). Un agente puede levantar el bloqueo cuando usted lo solicite con una nueva verificación de identidad.",
        "pt": "Pronto: o cartão {product} foi bloqueado temporariamente (verificado no sistema). Um agente pode retirar o bloqueio quando você solicitar, com uma nova verificação de identidade.",
    },
    "lock_refused": {
        "es": "Entendido, no bloqueamos la tarjeta. Quedó registrado en su caso. Si cambia de opinión, escríbanos.",
        "pt": "Entendido, não bloqueamos o cartão. Ficou registrado no seu caso. Se mudar de ideia, escreva para nós.",
    },
    "lock_ask_again": {
        "es": "No entendí su respuesta. ¿Desea que bloqueemos la tarjeta {product} ahora? Responda Sí o No.",
        "pt": "Não entendi sua resposta. Deseja que bloqueemos o cartão {product} agora? Responda Sim ou Não.",
    },
    "lock_which_card": {
        "es": " Como tiene varias tarjetas activas, no elegimos una por usted: un especialista confirmará con usted cuál bloquear.",
        "pt": " Como você tem vários cartões ativos, não escolhemos um por você: um especialista confirmará com você qual bloquear.",
    },
    "lock_pending": {
        "es": "No pudimos confirmar el bloqueo en el sistema. Un especialista lo completará y le confirmará; mientras tanto queda registrado como pendiente.",
        "pt": "Não conseguimos confirmar o bloqueio no sistema. Um especialista concluirá e confirmará; enquanto isso fica registrado como pendente.",
    },
    "case_ref": {"es": " Número de caso: {case_id}.", "pt": " Número do caso: {case_id}."},
    "other_charges": {
        "es": " Si también desconoce otro de los cargos que mencionó, escríbanos para abrir su caso.",
        "pt": " Se também não reconhece outra das cobranças que mencionou, escreva para nós para abrir o caso.",
    },
    "sibling_charges": {
        "es": " Además, {merchant} registra ese mismo día con la misma tarjeta o cuenta: {charges}. Si hay otro cargo que no reconoce, escríbanos indicando el monto para abrir su caso.",
        "pt": " Além disso, {merchant} registra nesse mesmo dia no mesmo cartão ou conta: {charges}. Se houver outra cobrança que você não reconhece, escreva para nós indicando o valor para abrir o caso.",
    },
    "case_exists": {
        "es": "Ese cargo ya tiene un caso de disputa abierto y en revisión, así que no abrimos otro. Número de caso: {case_id}.",
        "pt": "Essa cobrança já tem um caso de contestação aberto e em análise, portanto não abrimos outro. Número do caso: {case_id}.",
    },
    "handoff_ref": {"es": " Referencia: {handoff_id}.", "pt": " Referência: {handoff_id}."},
    "candidates_intro": {"es": " Estos son los movimientos recientes:", "pt": " Estes são os movimentos recentes:"},
    "candidates_pick": {"es": " Responda con el número del movimiento.", "pt": " Responda com o número do movimento."},
    "customer_gap": {
        "es": "No encontramos su perfil en el sistema de registro, así que no podemos evaluar la solicitud automáticamente. Un especialista se comunicará con usted.",
        "pt": "Não encontramos seu perfil no sistema de registro, portanto não podemos avaliar a solicitação automaticamente. Um especialista entrará em contato.",
    },
    "case_pending": {
        "es": "Su solicitud quedó pendiente: no pudimos confirmar el registro del caso en el sistema. Un especialista lo completará y le confirmará.",
        "pt": "Sua solicitação ficou pendente: não conseguimos confirmar o registro do caso no sistema. Um especialista concluirá e confirmará.",
    },
    "system_unavailable": {
        "es": "En este momento no pudimos consultar sus datos en el sistema del banco. Un especialista revisará su solicitud y se comunicará con usted.",
        "pt": "No momento não conseguimos consultar seus dados no sistema do banco. Um especialista analisará sua solicitação e entrará em contato.",
    },
}

OUTCOME_POLICY_EXPLANATION = "POLICY_EXPLANATION"  # the explainer answered, redirected or asked which topic; no case

STATE_NEW = "new"
STATE_AWAITING_CLARIFICATION = "awaiting_clarification"
STATE_AWAITING_LOCK = "awaiting_lock_confirmation"
STATE_CLOSED = "closed"
STATE_ESCALATED = "escalated"


@dataclass
class TurnResult:
    conversation_id: str
    state: str
    language: str
    reply: str
    policy_outcome: str | None = None
    escalation_reason: str | None = None
    clarification_reason: str | None = None
    cited_clauses: list[str] = field(default_factory=list)
    secondary_clauses: list[str] = field(default_factory=list)
    case_id: str | None = None
    handoff_id: str | None = None
    lock_offer: dict[str, Any] | None = None
    lock_status: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class DisputeOrchestrator:
    def __init__(self, gateway: BankingToolGateway, ops: OpsStore, extractor: KeywordIntentExtractor | None = None,
                 risk_scorer: Callable[[dict[str, Any], list[dict[str, Any]], dict[str, Any]], tuple[float, list[dict[str, Any]]]] | None = None,
                 today: date = date(2026, 6, 17), router: UnderstandRouter | None = None,
                 explainer: PolicyExplainer | None = None, zone_validator: RiskZoneValidator | None = None):
        self.gateway = gateway
        self.ops = ops
        self.today = today
        self.extractor = extractor or KeywordIntentExtractor(today=today)
        self.router = router  # the smart agent of TQ-008: picks Jev, Claude or the offline path per turn
        self.risk_scorer = risk_scorer  # (matched, history, profile) -> (ml_risk_score, risk_top_features); src.ml.fraud_risk.RiskScorer
        self.explainer = explainer  # the policy explainer (roadmap Task 5.1); None until its gate is calibrated (Task 4.1)
        self.zone_validator = zone_validator  # the check beside the risk score (src/tools/risk_zone.py); None records no zone verdict

    # ------------------------------------------------------------------ public
    def start_conversation(self, session: VerifiedSession, language: str = "es") -> dict[str, Any]:
        conv = self.ops.create_conversation(session.customer_id, language=language if language in ("es", "pt") else "es")
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="customer",
                       action="CONVERSATION_STARTED", details={"session_id": session.session_id})
        return conv

    def get_conversation(self, session: VerifiedSession, conversation_id: str) -> dict[str, Any]:
        conv = self._owned_conversation(session, conversation_id)
        conv["messages"] = self.ops.list_messages(conversation_id)
        return conv

    def handle_message(self, session: VerifiedSession, conversation_id: str, text: str) -> TurnResult:
        conv = self._owned_conversation(session, conversation_id)
        masked = PIIMasker.sanitize(text).sanitized_text
        routing = None
        if self.router is not None:
            history = [m["masked_text"] for m in self.ops.list_messages(conversation_id) if m["role"] == "customer"][-5:]
            understanding, routing = self.router.understand(text, conv["state"], history)
        else:
            understanding = self.extractor.extract(text)
        # The first message sets the language; later ones move it only on clear evidence, and a doubt is asked (TQ-042).
        low = text.lower()
        language = understanding.language if conv["state"] == STATE_NEW else conv["language"]
        shift = KeywordIntentExtractor.language_shift(low, language)
        if conv["state"] != STATE_NEW and shift == "switch":
            language = "pt" if language == "es" else "es"
        chosen_language = KeywordIntentExtractor.language_choice(text)
        language = chosen_language or language
        if language != conv["language"]:
            conv = self.ops.update_conversation(conversation_id, language=language)
        self.ops.add_message(conversation_id, "customer", masked, {**understanding.as_signals(), **(routing.as_dict() if routing else {})})
        if routing is not None:
            self.ops.audit(conversation_id=conversation_id, customer_id=session.customer_id, actor="system", action="ENGINE_ROUTED",
                           details=routing.as_dict())

        if chosen_language is not None:  # the message only names a language: nothing pending is answered or lost
            self.ops.audit(conversation_id=conversation_id, customer_id=session.customer_id, actor="system", action="LANGUAGE_CHANGED",
                           details={"language": language})
            result = TurnResult(conversation_id=conversation_id, state=conv["state"], language=language, reply=TEXT["language_set"][language],
                                signals=understanding.as_signals())
        elif conv["state"] == STATE_AWAITING_LOCK:
            result = self._handle_lock_confirmation(session, conv, understanding, language)
        else:
            if conv["state"] in (STATE_CLOSED, STATE_ESCALATED):
                conv = self.ops.update_conversation(conversation_id, state=STATE_NEW, candidate_ids=[],
                                                    matched_transaction_id=None, clarification_attempts=0)
            if self._asks_the_explainer(session, conv, understanding, masked):
                result = self._explain_policy(session, conv, understanding, masked, language)
            else:
                result = self._handle_dispute_turn(session, conv, understanding, masked, language)
        if chosen_language is None:
            self._tell_the_topics(session, conv, understanding, language, result)
        if chosen_language is None and shift == "ask":
            result.reply += TEXT["language_offer"][language]
        self.ops.add_message(conversation_id, "assistant", result.reply, {"state": result.state, "outcome": result.policy_outcome})
        return result

    def _tell_the_topics(self, session: VerifiedSession, conv: dict[str, Any], u: UnderstandResult, language: str, result: TurnResult) -> None:
        """TQ-044. With several topics in the message the reply says they are taken one by one, and a request this channel does
        not handle is named as such while the dispute goes on. The count goes to the audit log, never to the customer. The answer
        to the lock question carries no topics of its own."""
        if conv["state"] == STATE_AWAITING_LOCK or len(u.topics) < 2:
            return
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system", action="TOPICS_DETECTED",
                       details={"topic_count": len(u.topics), "topics": list(u.topics)})
        for topic in u.topics:
            if topic in OUT_OF_SCOPE_TOPICS and result.escalation_reason != "OUT_OF_SCOPE_INTENT":  # the abstention already names it
                label_es, label_pt = DisputePolicyEngine.OUT_OF_SCOPE_LABELS[topic]
                result.reply += TEXT["topic_not_related"][language].format(label=label_pt if language == "pt" else label_es)
        result.reply = TEXT["several_topics"][language] + result.reply

    # ------------------------------------------------------------ policy question
    def _asks_the_explainer(self, session: VerifiedSession, conv: dict[str, Any], u: UnderstandResult, masked: str) -> bool:
        """A policy question goes to the explainer in state new, with no charge of its own, and never when POL-ESC-LEGAL or
        POL-ESC-DISTRESS would fire on the message: those turns keep the dispute flow (roadmap section 4). During a clarification it
        goes there only when nothing was disputed before (a greeting that drew the list of recent charges); a dispute in progress keeps
        the dispute flow."""
        if self.explainer is None or not u.policy_question:
            return False
        if conv["state"] == STATE_AWAITING_CLARIFICATION:
            if self._disputed_earlier(conv):
                return False
        elif conv["state"] != STATE_NEW:
            return False
        if u.intent == "fuera_de_alcance" or (u.stolen_card_probability is not None and u.stolen_card_probability >= 0.40):
            return False
        prior_distress = self.ops.case_memory(session.customer_id).get("prior_distress_max_30d")
        return DisputePolicyEngine.message_escalation(masked, u.distress_score, prior_distress) is None

    def _disputed_earlier(self, conv: dict[str, Any]) -> bool:
        """Whether an earlier customer message of the conversation disputed something (an intent, an amount, a date, a loss),
        unlike a greeting. The last customer message is this turn's own."""
        earlier = [m for m in self.ops.list_messages(conv["conversation_id"]) if m["role"] == "customer"][:-1]
        for message in earlier:
            signals = message.get("signals") or {}
            if isinstance(signals, str):
                signals = json.loads(signals)
            if signals.get("policy_question"):
                continue  # a question about the rules disputes nothing, even when it names "un cargo" (TQ-041)
            if (signals.get("intent") not in (None, "consulta_general") or signals.get("amount_hint") is not None
                    or signals.get("date_hint") is not None or signals.get("stolen_card_claimed")):
                return True
        return False

    def _explain_policy(self, session: VerifiedSession, conv: dict[str, Any], u: UnderstandResult, masked: str,
                        language: str) -> TurnResult:
        """The explainer's answer from the corpus templates. It opens no case and leaves the conversation where it was: new, or
        a pending clarification whose listed charges the customer can still pick."""
        explanation = self.explainer.explain(masked, language)
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system",
                       action="POLICY_EXPLAINED",
                       details={"retriever": self.explainer.retriever.name, "action": explanation.action, "band": explanation.band.value,
                                "hits": [{"clause_id": h.clause_id, "score": round(h.score, 4)} for h in explanation.hits]})
        outcome = OUTCOME_ABSTENTION if explanation.action == "abstain" else OUTCOME_POLICY_EXPLANATION
        return TurnResult(conversation_id=conv["conversation_id"], state=conv["state"], language=language, reply=explanation.reply,
                          policy_outcome=outcome, cited_clauses=explanation.cited_clauses, signals=u.as_signals())

    # ------------------------------------------------------------ dispute turn
    def _handle_dispute_turn(self, session: VerifiedSession, conv: dict[str, Any], u: UnderstandResult, masked: str,
                             language: str) -> TurnResult:
        cid = conv["conversation_id"]
        try:
            profile = self.gateway.get_customer_profile(session)
            rows = self.gateway.search_customer_transactions(session, limit=25)
        except RecordNotFoundError:
            return self._escalate_data_gap(session, conv, masked, language, "DATA_GAP_CUSTOMER_PROFILE")
        except SYSTEM_OF_RECORD_UNAVAILABLE as exc:  # nothing was decided or written: a human takes the request (brief section 5)
            return self._escalate_data_gap(session, conv, masked, language, "SYSTEM_OF_RECORD_UNAVAILABLE",
                                           fact=f"The system of record did not answer ({type(exc).__name__})", text="system_unavailable")

        candidates, matched, named = self._identify_charge(conv, rows, u)
        siblings = self._sibling_charges(session.customer_id, matched, rows, named) if matched else []
        memory = self.ops.case_memory(session.customer_id)
        recent = self.ops.recent_disputed_transaction_ids(session.customer_id)
        if matched:
            recent = recent | {matched["transaction_id"]}
        recent = recent | {r["transaction_id"] for r in named}  # charges named at once count like charges disputed one by one
        ml_score, top_features = (self.risk_scorer(matched, rows, profile) if (self.risk_scorer and matched) else (0.0, []))
        scored = ml_score is not None  # None: the charge is outside the channels the model's threshold was calibrated on
        zone = self.zone_validator(matched, rows, profile) if (self.zone_validator and matched) else None

        policy_input = DisputePolicyInput(
            customer_id=session.customer_id,
            customer_segment=str(profile["segment"]),
            customer_country=str(profile["country"]),
            account_age_days=int(profile["account_age_days"]),
            complaints_last_90d=int(profile["complaints_last_90d"])
            + (0 if profile.get("complaints_include_ops_cases") else self._ops_cases_last_90d(session.customer_id)),
            transaction_id=matched["transaction_id"] if matched else None,
            transaction_date=date.fromisoformat(str(matched["process_date"])[:10]) if matched else None,
            transaction_amount=float(matched["amount"]) if matched else None,
            transaction_currency=matched["currency"] if matched else None,
            amount_usd=(float(matched["amount_usd"]) if matched and matched.get("amount_usd") is not None else None),
            transaction_type=matched["transaction_type"] if matched else None,
            transaction_status=matched["transaction_status"] if matched else None,
            ml_risk_score=ml_score if scored else 0.0,
            ml_risk_threshold=float(getattr(self.risk_scorer, "policy_threshold", 0.70) or 0.70),
            risk_top_features=top_features,
            recent_disputed_charges_count=max(1, len(recent)),
            customer_message=masked,
            candidate_charges_count=len(candidates),
            clarification_attempts=int(conv["clarification_attempts"]),
            dispute_intent=u.intent,
            intent_confidence=u.intent_confidence,
            out_of_scope_category=u.out_of_scope_category,
            is_stolen_reported=u.stolen_card_probability,  # None: keyword fallback inside the policy
            customer_distress_score=u.distress_score,
            current_date=self.today,
            **memory,
        )
        decision = DisputePolicyEngine.evaluate(policy_input)
        signals = {**u.as_signals(), "candidate_count": len(candidates), "ml_risk_score": ml_score}
        result = TurnResult(conversation_id=cid, state=conv["state"], language=language, reply=self._text(decision, language),
                            policy_outcome=decision.policy_outcome, escalation_reason=decision.escalation_reason,
                            clarification_reason=decision.clarification_reason, cited_clauses=list(decision.cited_clauses),
                            secondary_clauses=list(decision.secondary_clauses), signals=signals,
                            candidates=[self._public_candidate(c) for c in candidates[:5]])
        if zone is not None:  # beside the score and outside the decision and the reply: a record for the human agent (TQ-038)
            model_flags = self.risk_scorer is not None and scored and policy_input.ml_risk_score > policy_input.ml_risk_threshold
            self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="RISK_ZONE_VALIDATED",
                           details={"transaction_id": matched["transaction_id"], **zone.as_dict(),
                                    "ml_scored": self.risk_scorer is not None and scored, "ml_above_threshold": model_flags,
                                    "cross_check": cross_check(zone.in_risk_zone, model_flags)})

        if decision.policy_outcome == OUTCOME_CLARIFICATION:
            self.ops.update_conversation(cid, state=STATE_AWAITING_CLARIFICATION, candidate_ids=[c["transaction_id"] for c in candidates[:5]],
                                         clarification_attempts=int(conv["clarification_attempts"]) + 1)
            if decision.clarification_reason in ("NO_CANDIDATE_CHARGE", "MULTIPLE_CANDIDATE_CHARGES"):
                listed = candidates[:5] if candidates else rows[:5]
                result.candidates = [self._public_candidate(c) for c in listed]
                if listed:
                    self.ops.update_conversation(cid, candidate_ids=[c["transaction_id"] for c in listed])
                    result.reply += self._format_candidates(listed, language)
            result.state = STATE_AWAITING_CLARIFICATION
            several_named = len(u.amount_hints) > 1 and decision.clarification_reason == "MULTIPLE_CANDIDATE_CHARGES"
            self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="ASK_CLARIFICATION",
                           details={"reason": decision.clarification_reason, "clauses": decision.cited_clauses,
                                    "several_charges_named": several_named})
            if decision.card_lock_recommended:  # POL-AUT-LOCK travels with any outcome (S2, P5): the lock first, the charge after
                clarification, result.reply = result.reply, TEXT["lock_first"][language]
                if self._offer_lock(session, conv, decision, matched, language, result):
                    self.ops.update_conversation(cid, state=STATE_AWAITING_LOCK)
                    result.state, result.candidates = STATE_AWAITING_LOCK, []
                    return result
                # no card offered: the plain clarification, plus the note when a specialist confirms which card to lock
                result.reply = clarification + result.reply[len(TEXT["lock_first"][language]):]
            return result

        next_state = STATE_CLOSED
        if decision.policy_outcome == OUTCOME_ABSTENTION:
            self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="ABSTAIN",
                           details={"reason": decision.escalation_reason, "clauses": decision.cited_clauses,
                                    "data_quality_flag": decision.data_quality_flag})
        elif decision.policy_outcome == OUTCOME_ESCALATION:
            handoff_id = self._create_handoff(session, conv, decision, policy_input, profile, matched, masked, named=named, zone=zone,
                                              siblings=siblings)
            result.handoff_id = handoff_id
            result.reply += TEXT["handoff_ref"][language].format(handoff_id=handoff_id)
            result.actions.append({"action": "CREATE_HANDOFF", "handoff_id": handoff_id, "verified": True})
            next_state = STATE_ESCALATED
        elif decision.policy_outcome == OUTCOME_AUTONOMOUS:
            existing = self._open_case_for(session.customer_id, matched["transaction_id"])
            if existing:
                self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="DUPLICATE_CASE_PREVENTED",
                               details={"case_id": existing["case_id"], "transaction_id": matched["transaction_id"]})
                result.case_id = existing["case_id"]
                result.reply = TEXT["case_exists"][language].format(case_id=existing["case_id"])
                self.ops.update_conversation(cid, state=STATE_CLOSED, matched_transaction_id=matched["transaction_id"])
                result.state = STATE_CLOSED
                return result
            try:
                case_id = self._open_case(session, conv, decision, matched)
            except ActionVerificationError as exc:
                self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="OPEN_DISPUTE_FAILED",
                               details={"error": str(exc)}, verified=False)
                handoff_id = self._create_handoff(session, conv, decision, policy_input, profile, matched, masked,
                                                  reason_override="ACTION_VERIFICATION_FAILED", zone=zone, siblings=siblings)
                result.handoff_id = handoff_id
                result.reply = TEXT["case_pending"][language] + TEXT["handoff_ref"][language].format(handoff_id=handoff_id)
                result.policy_outcome = OUTCOME_ESCALATION
                result.escalation_reason = "ACTION_VERIFICATION_FAILED"
                next_state = STATE_ESCALATED
            else:
                result.case_id = case_id
                result.reply += TEXT["case_ref"][language].format(case_id=case_id)
                if conv["state"] == STATE_AWAITING_CLARIFICATION and self._pending_clarification_details(conv).get("several_charges_named"):
                    result.reply += TEXT["other_charges"][language]  # the customer picked one of the several charges they named
                if siblings:
                    charges = "; ".join(f"{float(r['amount']):,.2f} {r['currency']}" for r in siblings)
                    result.reply += TEXT["sibling_charges"][language].format(merchant=matched["merchant_name_raw"], charges=charges)
                    self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="SIBLING_CHARGES_LISTED",
                                   details={"transaction_id": matched["transaction_id"],
                                            "sibling_ids": [r["transaction_id"] for r in siblings]})
                result.actions.append({"action": "OPEN_DISPUTE", "case_id": case_id, "verified": True})

        if decision.card_lock_recommended:
            offered = self._offer_lock(session, conv, decision, matched, language, result)
            if offered:  # no clarification is pending after this outcome, so no earlier charge list may come back after the answer
                self.ops.update_conversation(cid, state=STATE_AWAITING_LOCK, matched_transaction_id=matched["transaction_id"] if matched else None,
                                             candidate_ids=[])
                result.state = STATE_AWAITING_LOCK
                return result
            if result.handoff_id and next_state == STATE_CLOSED:
                next_state = STATE_ESCALATED  # the card to lock is left to a specialist
        self.ops.update_conversation(cid, state=next_state, matched_transaction_id=matched["transaction_id"] if matched else None)
        result.state = next_state
        return result

    # ------------------------------------------------------ identify the charge
    def _identify_charge(self, conv: dict[str, Any], rows: list[dict[str, Any]], u: UnderstandResult):
        """Match the customer's hints against the session customer's own charges. Returns (candidates, matched or None, named):
        named holds the charges one message names at once when there are three or more, which count for POL-ESC-MULTI."""
        if u.intent == "fuera_de_alcance" or u.policy_question:  # a rules question names no charge of its own: never one of the list
            return [], None, []
        pool = rows
        if conv["state"] == STATE_AWAITING_CLARIFICATION and conv.get("candidate_ids"):
            prior = [r for r in rows if r["transaction_id"] in conv["candidate_ids"]]
            if u.selected_option and 1 <= u.selected_option <= len(prior):
                chosen = prior[u.selected_option - 1]
                return [chosen], chosen, []
            pool = prior or rows
        if len(u.amount_hints) > 1:
            several = self._several_named(pool, u)
            if several is not None:
                return several
        has_hint = u.amount_hint is not None or u.date_hint is not None
        candidates = list(pool)
        if u.amount_hint is not None:
            candidates = [r for r in candidates if self._amount_matches(r, u.amount_hint)]
        if u.date_hint is not None:
            candidates = [r for r in candidates if self._date_matches(r, u.date_hint, u.date_tolerance_days)]
        merchant_hits = [r for r in candidates if self._merchant_in_message(r, u)]
        if merchant_hits:
            candidates = merchant_hits
            has_hint = True
        if not has_hint:
            candidates = candidates[:5]
            if (len(candidates) == 1 and u.intent in ("consulta_general", "tarjeta_robada")
                    and (conv["state"] != STATE_AWAITING_CLARIFICATION or self._pending_clarification(conv) == "NO_CANDIDATE_CHARGE")):
                return [], None, []  # nothing names a charge, and a list of recent charges is no match: POL-CLARIFY asks (S3)
        if len(candidates) == 1:
            return candidates, candidates[0], []
        return candidates, None, []

    def _several_named(self, pool: list[dict[str, Any]], u: UnderstandResult):
        """A message that names several amounts. Three or more charges named without ambiguity count for POL-ESC-MULTI and the
        turn is decided on the first disputable one; otherwise every charge that matches one of the amounts is listed. None when
        at most one charge matches, so the single-amount reading decides."""
        per_amount = [[r for r in pool if self._amount_matches(r, amount)
                       and (u.date_hint is None or self._date_matches(r, u.date_hint, u.date_tolerance_days))]
                      for amount in u.amount_hints]
        named = list({m[0]["transaction_id"]: m[0] for m in per_amount if len(m) == 1}.values())
        if len(named) >= 3:
            matched = next((r for r in named if self._disputable(r)), named[0])
            return [matched], matched, named
        matching = {r["transaction_id"] for m in per_amount for r in m}
        candidates = [r for r in pool if r["transaction_id"] in matching]  # in listing order: the option reply reads it
        return (candidates, None, []) if len(candidates) > 1 else None

    @staticmethod
    def _disputable(row: dict[str, Any]) -> bool:
        """POL-DISP-TYPE and POL-WIN-60 as the gateway row tells them."""
        return (row.get("transaction_status") == DISPUTABLE_STATUS and row.get("transaction_type") in DISPUTABLE_TYPES
                and bool(row.get("is_within_60_days")))

    @staticmethod
    def _amount_matches(row: dict[str, Any], hint: float) -> bool:
        tolerance = max(0.01 * hint, 0.5)
        for key in ("amount", "amount_usd"):
            value = row.get(key)
            if value is not None and abs(float(value) - hint) <= tolerance:
                return True
        return False

    @staticmethod
    def _date_matches(row: dict[str, Any], hint: date, tolerance_days: int) -> bool:
        process_day = date.fromisoformat(str(row["process_date"])[:10])
        return abs((process_day - hint).days) <= max(tolerance_days, 1)

    @staticmethod
    def _known_merchant(row: dict[str, Any]) -> str | None:
        """The row's merchant in lower case, or None when the bank recorded none (gold writes Not Applicable or Unknown Merchant)."""
        raw = str(row.get("merchant_name_raw") or "").lower()
        return None if len(raw) < 3 or raw in ("unknown", "unknown merchant", "not applicable") else raw

    def _merchant_in_message(self, row: dict[str, Any], u: UnderstandResult) -> bool:
        merchant = self._known_merchant(row)
        return merchant is not None and merchant in u.message_lower

    def _sibling_charges(self, customer_id: str, matched: dict[str, Any], rows: list[dict[str, Any]],
                         named: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The customer's other disputable charges on the product, merchant and bank process day of the matched one, with no
        open case and not named in the message. They are told, never counted: POL-ESC-MULTI counts disputed charges (TQ-039)."""
        merchant = self._known_merchant(matched)
        if merchant is None:
            return []
        told = {matched["transaction_id"]} | {r["transaction_id"] for r in named}
        return [r for r in rows
                if r["transaction_id"] not in told and r.get("product_id") == matched.get("product_id")
                and self._known_merchant(r) == merchant and str(r["process_date"])[:10] == str(matched["process_date"])[:10]
                and self._disputable(r) and self._open_case_for(customer_id, r["transaction_id"]) is None]

    # --------------------------------------------------------------------- act
    def _open_case(self, session: VerifiedSession, conv: dict[str, Any], decision: DisputePolicyDecision, matched: dict[str, Any]) -> str:
        case_id = self.ops.insert_case(
            conversation_id=conv["conversation_id"], customer_id=session.customer_id, transaction_id=matched["transaction_id"],
            product_id=matched.get("product_id"), case_values=decision.case_values, claimed_amount=float(matched["amount"]),
            currency=matched["currency"], amount_usd=float(matched["amount_usd"]), cited_clauses=decision.cited_clauses,
            provisional_credit_candidate=decision.provisional_credit_candidate,
            provisional_credit_amount_usd=decision.provisional_credit_amount_usd,
        )
        persisted = self.ops.get_case(case_id)  # VERIFY: read back before telling the customer
        if not persisted or persisted["status"] != decision.case_values["status"]:
            raise ActionVerificationError(f"Dispute case {case_id} could not be verified in the ops store.")
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system", action="OPEN_DISPUTE",
                       details={"case_id": case_id, "transaction_id": matched["transaction_id"], "clauses": decision.cited_clauses,
                                "provisional_credit_candidate": decision.provisional_credit_candidate}, verified=True)
        return case_id

    def _offer_lock(self, session: VerifiedSession, conv: dict[str, Any], decision: DisputePolicyDecision, matched: dict[str, Any] | None,
                    language: str, result: TurnResult) -> bool:
        product_id = matched.get("product_id") if matched else None
        try:
            cards = self.gateway.list_customer_cards(session)
        except SYSTEM_OF_RECORD_UNAVAILABLE as exc:  # no card list, no offer; the outcome of the turn stands
            self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system", action="LOCK_NOT_OFFERED",
                           details={"reason": decision.card_lock_reason, "why": "system of record unavailable", "error": str(exc)})
            return False
        card_ids = [c["product_id"] for c in cards]
        if product_id not in card_ids:  # the charge sits on no active card: only a customer's one card is beyond doubt
            if len(card_ids) > 1:
                self._hand_over_the_card_choice(session, conv, decision, matched, card_ids, language, result)
                return False
            product_id = card_ids[0] if card_ids else None
        if product_id is None:
            self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system",
                           action="LOCK_NOT_OFFERED", details={"reason": decision.card_lock_reason, "why": "no active card product"})
            return False
        lock_id = self.ops.insert_lock(conversation_id=conv["conversation_id"], customer_id=session.customer_id, product_id=product_id,
                                       reason=decision.card_lock_reason or "STOLEN_CARD_CLAIM", status="offered")
        self.ops.update_conversation(conv["conversation_id"], pending_lock_product_id=product_id)
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system", action="LOCK_OFFERED",
                       details={"lock_id": lock_id, "product_id": product_id, "reason": decision.card_lock_reason,
                                "required_authentication": decision.card_lock_required_authentication})
        key = "lock_offer_multi" if decision.card_lock_reason == "MULTI_CHARGE_FRAUD" else "lock_offer"
        result.reply += TEXT[key][language].format(product=self._card_label(product_id))
        result.lock_offer = {"lock_id": lock_id, "product_id": product_id, "reason": decision.card_lock_reason,
                             "required_authentication": decision.card_lock_required_authentication}
        result.lock_status = "offered"
        return True

    def _hand_over_the_card_choice(self, session: VerifiedSession, conv: dict[str, Any], decision: DisputePolicyDecision,
                                   matched: dict[str, Any] | None, card_ids: list[str], language: str, result: TurnResult) -> None:
        """Several active cards and none holds the charge: the bot never picks one. A specialist confirms the card with the
        customer through a verified handoff, or through the turn's own handoff when it already escalated (that packet
        already recommends the lock)."""
        cid = conv["conversation_id"]
        self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="LOCK_NOT_OFFERED",
                       details={"reason": decision.card_lock_reason, "why": "several active cards, none tied to the charge",
                                "active_cards": len(card_ids)})
        result.reply += TEXT["lock_which_card"][language]
        if result.handoff_id:
            return
        requests = [m["masked_text"] for m in self.ops.list_messages(cid) if m["role"] == "customer"]
        facts = ["Customer authenticated via a valid session token",
                 f"Customer holds {len(card_ids)} active cards and the report names none of them"]
        if matched:
            facts.append(f"Disputed charge {matched['transaction_id']} is on product {matched['product_id']}, which is not an active card")
        packet = {"customer_id": session.customer_id, "customer_request": requests[-1] if requests else "",
                  "escalation_reason": "LOCK_CARD_AMBIGUOUS", "verified_facts": facts, "applicable_policy_clauses": ["POL-AUT-LOCK"],
                  "card_lock": {"recommended": True, "reason": decision.card_lock_reason, "status": "not_offered",
                                "candidate_products": card_ids},
                  "open_questions": ["Which card does the customer want to lock?"]}
        handoff_id = self._insert_verified_handoff(session, cid, "LOCK_CARD_AMBIGUOUS", packet)
        result.handoff_id = handoff_id
        result.reply += TEXT["handoff_ref"][language].format(handoff_id=handoff_id)
        result.actions.append({"action": "CREATE_HANDOFF", "handoff_id": handoff_id, "verified": self.ops.get_handoff(handoff_id) is not None})

    def _handle_lock_confirmation(self, session: VerifiedSession, conv: dict[str, Any], u: UnderstandResult, language: str) -> TurnResult:
        cid = conv["conversation_id"]
        product_id = conv.get("pending_lock_product_id")
        offered = [lk for lk in self.ops.list_locks(conversation_id=cid) if lk["status"] == "offered"]
        lock_id = offered[0]["lock_id"] if offered else None
        has_handoff = any(h["conversation_id"] == cid for h in self.ops.list_handoffs())
        final_state = STATE_ESCALATED if has_handoff else STATE_CLOSED
        result = TurnResult(conversation_id=cid, state=conv["state"], language=language, reply="", signals=u.as_signals())
        if u.said_yes and not u.said_no:
            reason_code = offered[0]["reason"] if offered else "STOLEN_CARD_CLAIM"
            try:
                outcome = self.gateway.execute_lock_card(session, product_id, reason="Preventive temporary lock confirmed by the customer",
                                                         lock_id=lock_id, reason_code=reason_code)
            except (ActionVerificationError, UnauthorizedAccessError, *SYSTEM_OF_RECORD_UNAVAILABLE) as exc:  # a timeout leaves the write unverified
                self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="LOCK_CARD_FAILED",
                               details={"product_id": product_id, "error": str(exc)}, verified=False)
                # always its own handoff: the customer hears that a specialist will finish the lock, even when an earlier episode escalated
                packet = {"customer_id": session.customer_id, "customer_request": self._lock_offer_request(cid),
                          "escalation_reason": "ACTION_VERIFICATION_FAILED", "action": "LOCK_CARD", "product_id": product_id,
                          "verified_facts": ["Customer authenticated via a valid session token", "The customer confirmed the lock",
                                             f"The lock could not be verified in the system of record ({type(exc).__name__})"],
                          "applicable_policy_clauses": ["POL-AUT-LOCK"], "error": str(exc)}
                if conv.get("candidate_ids") and not conv.get("matched_transaction_id"):  # the charge question the lock offer deferred
                    packet["pending_clarification"] = {"reason": self._pending_clarification(conv), "candidate_ids": conv["candidate_ids"]}
                result.handoff_id = self._insert_verified_handoff(session, cid, "ACTION_VERIFICATION_FAILED", packet)
                result.reply = TEXT["lock_pending"][language]
                result.lock_status = "pending"
                result.state = STATE_ESCALATED
                self.ops.update_conversation(cid, state=STATE_ESCALATED, pending_lock_product_id=None)
                return result
            if lock_id:
                self.ops.update_lock(lock_id, "locked", verified=True)
            self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="customer", action="LOCK_CARD",
                           details={"lock_id": lock_id, "product_id": product_id, "reason_code": reason_code,
                                    "read_back_status": outcome["status"]}, verified=True)
            result.reply = TEXT["lock_done"][language].format(product=self._card_label(product_id))
            result.lock_status = "locked"
            result.actions.append({"action": "LOCK_CARD", "product_id": product_id, "verified": True})
        elif u.said_no:  # read without the dispute phrases, so "no reconozco un cargo" is no refusal
            if lock_id:
                self.ops.update_lock(lock_id, "refused")
            self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="customer", action="LOCK_REFUSED",
                           details={"lock_id": lock_id, "product_id": product_id})
            result.reply = TEXT["lock_refused"][language]
            result.lock_status = "refused"
        else:
            result.reply = TEXT["lock_ask_again"][language].format(product=self._card_label(product_id))
            result.lock_status = "offered"
            result.state = STATE_AWAITING_LOCK
            return result
        if conv.get("candidate_ids") and not conv.get("matched_transaction_id"):  # only a lock offered on a clarification keeps the list
            return self._resume_clarification(session, conv, result, language)
        self.ops.update_conversation(cid, state=final_state, pending_lock_product_id=None)
        result.state = final_state
        return result

    def _pending_clarification(self, conv: dict[str, Any]) -> str | None:
        """The reason of the last POL-CLARIFY question asked in the conversation, from its audit row."""
        return self._pending_clarification_details(conv).get("reason")

    def _pending_clarification_details(self, conv: dict[str, Any]) -> dict[str, Any]:
        """The audit details of the last POL-CLARIFY question asked in the conversation (empty when none was asked)."""
        return next((a["details"] for a in reversed(self.ops.list_audit(conversation_id=conv["conversation_id"], limit=1000))
                     if a["action"] == "ASK_CLARIFICATION"), {})

    def _lock_offer_request(self, cid: str) -> str:
        """The customer's message of the turn that offered the pending lock (the report of the loss), for a handoff packet."""
        offered_at = next((a["created_at"] for a in reversed(self.ops.list_audit(conversation_id=cid, limit=1000)) if a["action"] == "LOCK_OFFERED"), None)
        before = [m["masked_text"] for m in self.ops.list_messages(cid) if m["role"] == "customer" and (offered_at is None or m["created_at"] <= offered_at)]
        return before[-1] if before else ""

    def _insert_verified_handoff(self, session: VerifiedSession, cid: str, reason: str, packet: dict[str, Any]) -> str:
        """Insert a handoff and read it back before the turn tells the customer that a specialist has it."""
        handoff_id = self.ops.insert_handoff(conversation_id=cid, customer_id=session.customer_id, escalation_reason=reason, packet=packet)
        self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="CREATE_HANDOFF",
                       details={"handoff_id": handoff_id, "reason": reason}, verified=self.ops.get_handoff(handoff_id) is not None)
        return handoff_id

    def _resume_clarification(self, session: VerifiedSession, conv: dict[str, Any], result: TurnResult, language: str) -> TurnResult:
        """After the lock answer, the POL-CLARIFY question the offer deferred: same reason, same listed charges, no new attempt."""
        cid = conv["conversation_id"]
        reason = self._pending_clarification(conv) or "MULTIPLE_CANDIDATE_CHARGES"
        listed: list[dict[str, Any]] = []
        if reason in ("NO_CANDIDATE_CHARGE", "MULTIPLE_CANDIDATE_CHARGES"):
            try:  # the listing order is the one _identify_charge reads an option number against
                listed = [r for r in self.gateway.search_customer_transactions(session, limit=25) if r["transaction_id"] in conv["candidate_ids"]]
            except SYSTEM_OF_RECORD_UNAVAILABLE as exc:  # the lock answer stands; a human takes the charge question
                packet = {"customer_id": session.customer_id, "customer_request": self._lock_offer_request(cid),
                          "escalation_reason": "SYSTEM_OF_RECORD_UNAVAILABLE",
                          "verified_facts": ["Customer authenticated via a valid session token", f"Card lock {result.lock_status} on the customer's answer",
                                             f"The system of record did not answer when listing the charges again ({type(exc).__name__})"],
                          "applicable_policy_clauses": ["POL-CLARIFY", "POL-AUT-LOCK"],
                          "pending_clarification": {"reason": reason, "candidate_ids": conv["candidate_ids"]}, "error": str(exc)}
                handoff_id = self._insert_verified_handoff(session, cid, "SYSTEM_OF_RECORD_UNAVAILABLE", packet)
                result.reply += " " + TEXT["system_unavailable"][language] + TEXT["handoff_ref"][language].format(handoff_id=handoff_id)
                result.handoff_id, result.state = handoff_id, STATE_ESCALATED
                self.ops.update_conversation(cid, state=STATE_ESCALATED, pending_lock_product_id=None)
                return result
        es, pt = DisputePolicyEngine.CLARIFICATION_TEXTS[reason]
        result.reply += " " + (pt if language == "pt" else es) + (self._format_candidates(listed, language) if listed else "")
        result.candidates = [self._public_candidate(r) for r in listed]
        result.clarification_reason, result.state = reason, STATE_AWAITING_CLARIFICATION
        self.ops.update_conversation(cid, state=STATE_AWAITING_CLARIFICATION, pending_lock_product_id=None)
        return result

    # ---------------------------------------------------------------- escalate
    def _create_handoff(self, session: VerifiedSession, conv: dict[str, Any], decision: DisputePolicyDecision, policy_input: DisputePolicyInput,
                        profile: dict[str, Any], matched: dict[str, Any] | None, masked: str, reason_override: str | None = None,
                        named: list[dict[str, Any]] | None = None, zone: RiskZoneVerdict | None = None,
                        siblings: list[dict[str, Any]] | None = None) -> str:
        now = datetime.utcnow().replace(microsecond=0).isoformat()
        reason = reason_override or decision.escalation_reason or "UNSPECIFIED"
        facts = ["Customer authenticated via a valid session token"]
        evidence = [f"gold_customers row {session.customer_id} read at {now}"]
        triggering = None
        if matched:
            process_day = date.fromisoformat(str(matched["process_date"])[:10])
            days = (self.today - process_day).days
            facts.append(f"Charge process day {process_day.isoformat()}, {days} days before {self.today.isoformat()} "
                         f"({'within' if 0 <= days <= 60 else 'outside'} the 60-day window)")
            evidence.append(f"gold_transactions row {matched['transaction_id']} read at {now}")
            triggering = TriggeringTransaction(
                transaction_id=matched["transaction_id"], amount_original=float(matched["amount"]), currency=str(matched["currency"]),
                amount_usd=float(matched["amount_usd"]) if matched.get("amount_usd") is not None else None,
                merchant_name=matched.get("merchant_name"),
                transaction_date=str(matched["transaction_date"]),
            )
        facts.append(f"Customer has {policy_input.complaints_last_90d} complaints in the last 90 days")
        if self.risk_scorer is None:  # no model file: POL-ESC-ML-RISK was not evaluated, so no score is a fact
            facts.append("ML risk score: not scored, no risk model is loaded")
        elif matched is None:
            facts.append("ML risk score: not scored, no charge identified")
        elif matched.get("channel") not in getattr(self.risk_scorer, "channels", (matched.get("channel"),)):
            facts.append(f"ML risk score: not scored, the model scores {' and '.join(self.risk_scorer.channels)} charges only")
        else:
            facts.append(f"ML risk score: {policy_input.ml_risk_score:.2f} (escalation threshold {policy_input.ml_risk_threshold:.2f})")
        if zone is not None:
            facts.append(zone.fact())
        facts.append(f"{policy_input.recent_disputed_charges_count} distinct charge(s) disputed within 48 hours")
        if named:
            facts.append(f"Charges named in the customer's message: {', '.join(r['transaction_id'] for r in named)}")
        if siblings:
            facts.append(f"{len(siblings)} other undisputed charge(s) on the same product, merchant and process day: "
                         f"{', '.join(r['transaction_id'] for r in siblings)}")
        questions = self._questions_for(reason, decision)
        packet = StructuredHandoffPacket(
            handoff_id="", customer_id=session.customer_id, customer_name=str(profile.get("full_name") or session.name),
            segment=str(profile["segment"]), country=str(profile["country"]), escalation_reason=reason, customer_request=masked,
            triggering_transaction=triggering, verified_facts=facts, supporting_evidence=evidence,
            applicable_policy_clauses=list(decision.cited_clauses), secondary_clauses=list(decision.secondary_clauses),
            provisional_credit_recommendation=({"amount_usd": decision.provisional_credit_amount_usd, "clause": "POL-AUT-150"}
                                               if decision.provisional_credit_candidate else None),
            risk_explanation=({"score": policy_input.ml_risk_score, "threshold": policy_input.ml_risk_threshold, "top_features": decision.risk_top_features}
                              if decision.risk_top_features else None),
            case_memory=decision.case_memory,
            card_lock=({"recommended": True, "reason": decision.card_lock_reason, "status": "offered"} if decision.card_lock_recommended else None),
            unresolved_questions_for_customer=questions,
        )
        handoff_id = self.ops.insert_handoff(conversation_id=conv["conversation_id"], customer_id=session.customer_id,
                                             escalation_reason=reason, packet=packet.model_dump(mode="json"))
        persisted = self.ops.get_handoff(handoff_id)  # VERIFY
        if not persisted:
            raise ActionVerificationError(f"Handoff {handoff_id} could not be verified in the ops store.")
        self.ops.audit(conversation_id=conv["conversation_id"], customer_id=session.customer_id, actor="system", action="CREATE_HANDOFF",
                       details={"handoff_id": handoff_id, "reason": reason, "clauses": decision.cited_clauses,
                                "secondary_clauses": decision.secondary_clauses}, verified=True)
        return handoff_id

    def _escalate_data_gap(self, session: VerifiedSession, conv: dict[str, Any], masked: str, language: str, reason: str,
                           fact: str = "Customer profile missing from the system of record", text: str = "customer_gap") -> TurnResult:
        cid = conv["conversation_id"]
        packet = {"customer_id": session.customer_id, "customer_request": masked, "escalation_reason": reason,
                  "verified_facts": ["Customer authenticated via a valid session token", fact],
                  "applicable_policy_clauses": []}
        handoff_id = self.ops.insert_handoff(conversation_id=cid, customer_id=session.customer_id, escalation_reason=reason, packet=packet)
        self.ops.audit(conversation_id=cid, customer_id=session.customer_id, actor="system", action="CREATE_HANDOFF",
                       details={"handoff_id": handoff_id, "reason": reason}, verified=True)
        self.ops.update_conversation(cid, state=STATE_ESCALATED)
        return TurnResult(conversation_id=cid, state=STATE_ESCALATED, language=language,
                          reply=TEXT[text][language] + TEXT["handoff_ref"][language].format(handoff_id=handoff_id),
                          policy_outcome=OUTCOME_ESCALATION, escalation_reason=reason, handoff_id=handoff_id,
                          actions=[{"action": "CREATE_HANDOFF", "handoff_id": handoff_id, "verified": True}])

    @staticmethod
    def _questions_for(reason: str, decision: DisputePolicyDecision) -> list[str]:
        questions = ["Does the customer recognize any other charges on that statement date?"]
        if decision.card_lock_recommended or reason == "MULTIPLE_CHARGES_48H":
            questions.insert(0, "Did the customer possess the physical card at the time of the transaction?")
        if reason == "SEVERE_DISTRESS":
            questions.insert(0, "Does the customer need immediate assistance beyond the dispute?")
        if reason == "REGULATOR_OR_LEGAL_CITING":
            questions.insert(0, "Has the customer already filed with the regulator or started legal action?")
        return questions

    # ----------------------------------------------------------------- helpers
    def _owned_conversation(self, session: VerifiedSession, conversation_id: str) -> dict[str, Any]:
        conv = self.ops.get_conversation(conversation_id)
        if conv is None or conv["customer_id"] != session.customer_id:
            # same outward error for "not found" and "not yours", so ids cannot be probed (POL-SEC-SESSION)
            self.ops.audit(conversation_id=conversation_id, customer_id=session.customer_id, actor="system",
                           action="CONVERSATION_ACCESS_DENIED", details={"exists": conv is not None})
            raise UnauthorizedAccessError("Conversation not found.")
        return conv

    def _open_case_for(self, customer_id: str, transaction_id: str) -> dict[str, Any] | None:
        for case in self.ops.list_cases(customer_id=customer_id):
            if case["transaction_id"] == transaction_id and case["status"] in ("Open", "In Progress"):
                return case
        return None

    def _ops_cases_last_90d(self, customer_id: str) -> int:
        """Same rule as ops.v_customer_policy_facts: cases created on or after the business day minus 90 days."""
        since = self.today - timedelta(days=90)
        return len([c for c in self.ops.list_cases(customer_id=customer_id) if date.fromisoformat(str(c["created_at"])[:10]) >= since])

    @staticmethod
    def _text(decision: DisputePolicyDecision, language: str) -> str:
        return decision.explanation_pt if language == "pt" else decision.explanation_es

    @staticmethod
    def _card_label(product_id: str | None) -> str:
        return f"...{product_id[-4:]}" if product_id else "principal"

    @staticmethod
    def _public_candidate(row: dict[str, Any]) -> dict[str, Any]:
        return {"transaction_id": row["transaction_id"], "process_date": str(row["process_date"])[:10], "amount": float(row["amount"]),
                "currency": row["currency"], "amount_usd": (float(row["amount_usd"]) if row.get("amount_usd") is not None else None),
                "merchant_name": row.get("merchant_name_raw") or "Unknown", "transaction_type": row.get("transaction_type"),
                "transaction_status": row.get("transaction_status")}

    def _format_candidates(self, rows: list[dict[str, Any]], language: str) -> str:
        lines = []
        for i, r in enumerate(rows, start=1):
            day = str(r["process_date"])[:10]
            lines.append(f" {i}) {day}, {float(r['amount']):,.2f} {r['currency']}, {r.get('merchant_name_raw') or 'Unknown'}")
        return TEXT["candidates_intro"][language] + "".join(lines) + TEXT["candidates_pick"][language]
