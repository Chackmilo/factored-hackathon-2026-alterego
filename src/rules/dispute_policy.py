"""
Synthetic Dispute Policy Engine for the AlterEgo dispute intake stack.
Implements the rules of Section 2 / Decision 4 of the Team Brief (policy v2.3).
Spec and traceability matrix: docs/specs/dispute-policy-v2.3.md.

Clause order (the first clause that decides the case wins):
- POL-ESC-LEGAL: regulator or legal action cited -> HITL, before the window.
- POL-CLARIFY / POL-ESC-AMBIG: identify the charge; ambiguity asks, twice, then HITL.
- POL-DISP-TYPE: only Approved debits are disputable; data errors and out of scope abstain.
- POL-WIN-60: process_date within 60 calendar days of today.
- POL-ESC-500, POL-ESC-ML-RISK, POL-ESC-MULTI, POL-ESC-DISTRESS: mandatory HITL.
- POL-AUT-150: provisional-credit candidate flag (a human approves), then POL-AUT-INTAKE.
- POL-AUT-LOCK: card lock recommendation, independent of the outcome.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

OUTCOME_AUTONOMOUS = "AUTONOMOUS_RESOLUTION"
OUTCOME_ABSTENTION = "SAFE_POLICY_ABSTENTION"
OUTCOME_ESCALATION = "MANDATORY_HITL_ESCALATION"
OUTCOME_CLARIFICATION = "CLARIFICATION_REQUIRED"

ACTION_OPEN_DISPUTE = "OPEN_DISPUTE_ONLY"
ACTION_ESCALATE = "ESCALATE"
ACTION_ABSTAIN = "ABSTAIN"
ACTION_ASK = "ASK_CLARIFICATION"

DISPUTABLE_TYPES = frozenset({"Purchase", "Payment", "Withdrawal", "Transfer"})
DISPUTABLE_STATUS = "Approved"

# Closed set of unsupported categories (brief v2.3 POL-DISP-TYPE, team resolution P4 of 27-Sep).
OUT_OF_SCOPE_CATEGORIES = frozenset({
    "prestamo_o_credito", "saldo_o_extracto", "inversion_o_seguro",
    "soporte_de_tarjeta", "otro_producto", "no_determinado",
})

# Team-written fallback keyword lists (assumption S8), used only when the Jev signal is absent.
DISTRESS_KEYWORDS = (
    "desesperado", "desesperada", "no tengo para comer", "no tengo dinero", "me quedé sin nada", "me quede sin nada",
    "emergencia", "urgente",
    "não tenho como", "nao tenho como", "não tenho dinheiro", "nao tenho dinheiro", "fiquei sem nada", "emergência",
)
STOLEN_CARD_KEYWORDS = (
    "me robaron", "robaron", "robo", "perdí la tarjeta", "perdi la tarjeta", "extravié", "extravie",
    "roubaram", "roubo", "perdi o cartão", "perdi o cartao", "extraviei",
)

@dataclass
class DisputePolicyInput:
    # Customer facts, read from the system of record by the caller (never from the token).
    customer_id: str
    customer_segment: str  # 'Premium', 'Plus', 'Basic', 'Student'
    customer_country: str  # 'Colombia', 'México', 'Argentina'
    account_age_days: int
    complaints_last_90d: int
    # The single matched charge. None until POL-CLARIFY has identified exactly one candidate.
    transaction_id: str | None = None
    transaction_date: Any | None = None  # datetime (UTC, shifted 6 h back) or date == process_date
    transaction_amount: float | None = None
    transaction_currency: str | None = None
    amount_usd: float | None = None
    transaction_type: str | None = None
    transaction_status: str | None = None
    # Learned and conversational signals; typed contracts fed by fixtures until the components exist.
    ml_risk_score: float = 0.0
    ml_risk_threshold: float = 0.70  # the transferred model sets a percentile of the bank window (spec section 6); 0.70 is the brief's default
    risk_top_features: list[dict[str, Any]] = field(default_factory=list)
    recent_disputed_charges_count: int = 1
    customer_message: str = ""
    candidate_charges_count: int = 1
    clarification_attempts: int = 0
    dispute_intent: str | None = None
    intent_confidence: float | None = None
    out_of_scope_category: str | None = None
    is_stolen_reported: float | None = None
    customer_distress_score: float | None = None
    # Case memory: facts the system recorded in earlier conversations (team resolution P3).
    prior_distress_max_30d: float | None = None
    prior_escalations_180d: int = 0
    prior_cases_180d: int = 0
    prior_lock_refused: bool = False
    current_date: date = date(2026, 6, 17)  # Dataset reference anchor date

@dataclass
class DisputePolicyDecision:
    is_eligible: bool
    policy_outcome: str  # OUTCOME_* constants
    provisional_credit_candidate: bool
    provisional_credit_amount_usd: float
    cited_clauses: list[str] = field(default_factory=list)
    escalation_reason: str | None = None
    action_required: str = "NONE"  # ACTION_* constants
    explanation_es: str = ""
    explanation_pt: str = ""
    secondary_clauses: list[str] = field(default_factory=list)
    clarification_reason: str | None = None
    data_quality_flag: str | None = None
    card_lock_recommended: bool = False
    card_lock_reason: str | None = None
    card_lock_required_authentication: str | None = None
    required_authentication: str = "SESSION"
    case_values: dict[str, str] = field(default_factory=dict)
    risk_top_features: list[dict[str, Any]] = field(default_factory=list)
    case_memory: dict[str, Any] = field(default_factory=dict)

class DisputePolicyEngine:
    """
    Deterministic dispute intake policy evaluator.
    No model hallucinations; rule evaluations produce traceable audit clauses.
    """

    # Risk tier and authentication per supported action (team resolution P5). Enforced by gateway and console;
    # UNLOCK_CARD and APPROVE_CREDIT_CANDIDATE are console actions of a human agent, never chat actions.
    ACTION_AUTH_MATRIX: dict[str, tuple[str, str]] = {
        ACTION_OPEN_DISPUTE: ("LOW", "SESSION"),
        ACTION_ESCALATE: ("LOW", "SESSION"),
        ACTION_ASK: ("LOW", "SESSION"),
        ACTION_ABSTAIN: ("LOW", "SESSION"),
        "LOCK_CARD": ("MEDIUM", "SESSION_AND_CUSTOMER_CONFIRMATION"),
        "UNLOCK_CARD": ("HIGH", "STEP_UP_AND_AGENT"),
        "APPROVE_CREDIT_CANDIDATE": ("HIGH", "AGENT_ROLE"),
    }

    REGULATOR_OR_LEGAL_KEYWORDS = [
        r"\b(condusef|sfc|superintendencia|bcra|procon)\b",
        r"\b(demanda|abogado|tribunal|denuncia\s+penal)\b",
        r"\b(processo|advogado|denúncia)\b",
    ]

    CLARIFICATION_TEXTS = {
        "NO_CANDIDATE_CHARGE": (
            "No encontramos un cargo que coincida con su descripción. ¿Podría indicarnos la fecha, el monto o el comercio del movimiento?",
            "Não encontramos uma cobrança que corresponda à sua descrição. Poderia informar a data, o valor ou o estabelecimento?",
        ),
        "MULTIPLE_CANDIDATE_CHARGES": (
            "Encontramos varios cargos que podrían coincidir. ¿Cuál de ellos desea disputar?",
            "Encontramos várias cobranças que podem corresponder. Qual delas você deseja contestar?",
        ),
        "LOW_INTENT_CONFIDENCE": (
            "Para ayudarle bien necesitamos entender mejor su solicitud. ¿Podría contarnos con más detalle qué ocurrió?",
            "Para ajudar melhor, precisamos entender sua solicitação. Poderia contar com mais detalhes o que aconteceu?",
        ),
        "STOLEN_CARD_AMBIGUOUS": (
            "Antes de continuar: ¿aún tiene su tarjeta física con usted?",
            "Antes de continuar: você ainda está com o cartão físico?",
        ),
    }

    OUT_OF_SCOPE_LABELS = {
        "prestamo_o_credito": ("préstamos y créditos", "empréstimos e créditos"),
        "saldo_o_extracto": ("saldos y extractos", "saldos e extratos"),
        "inversion_o_seguro": ("inversiones y seguros", "investimentos e seguros"),
        "soporte_de_tarjeta": ("soporte de tarjeta (PIN, reposición, entrega)", "suporte do cartão (PIN, reposição, entrega)"),
        "otro_producto": ("otros productos", "outros produtos"),
        "no_determinado": ("otros temas", "outros assuntos"),
    }

    @classmethod
    def _abstention(cls, policy_input: DisputePolicyInput, reason: str, explanation_es: str, explanation_pt: str,
                    cited_clauses: list[str] | None = None, data_quality_flag: str | None = None) -> DisputePolicyDecision:
        return DisputePolicyDecision(
            is_eligible=False,
            policy_outcome=OUTCOME_ABSTENTION,
            provisional_credit_candidate=False,
            provisional_credit_amount_usd=0.0,
            cited_clauses=cited_clauses or ["POL-DISP-TYPE"],
            escalation_reason=reason,
            data_quality_flag=data_quality_flag,
            action_required=ACTION_ABSTAIN,
            explanation_es=explanation_es,
            explanation_pt=explanation_pt,
        )

    @staticmethod
    def _case_values(policy_input: DisputePolicyInput) -> dict[str, str]:
        """Data-dictionary values for the complaint row (brief v2.3, autonomous action 6)."""
        subcategory = "Cobro indebido" if policy_input.dispute_intent == "cobro_indebido" else "Cargo no reconocido"
        return {"case_type": "Claim", "category": "Transactions", "subcategory": subcategory,
                "reception_channel": "App", "status": "Open"}

    @staticmethod
    def _intake_text_es(policy_input: DisputePolicyInput) -> str:
        return (f"Su solicitud de disputa por el cargo de {policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} "
                "quedó registrada y está en revisión. Recibirá respuesta formal en 3 a 5 días hábiles.")

    @staticmethod
    def _intake_text_pt(policy_input: DisputePolicyInput) -> str:
        return (f"Sua solicitação de contestação da cobrança de {policy_input.transaction_amount:,.2f} {policy_input.transaction_currency} "
                "foi registrada e está em análise. Você receberá resposta formal em 3 a 5 dias úteis.")

    @classmethod
    def _escalations(cls, policy_input: DisputePolicyInput, msg_lower: str) -> list[tuple[str, str, str, str]]:
        """Every mandatory escalation clause that applies, in the brief's order (POL-ESC-500 first)."""
        fired: list[tuple[str, str, str, str]] = []
        if policy_input.amount_usd > 500.0:
            fired.append((
                "POL-ESC-500", "AMOUNT_EXCEEDS_500_USD",
                f"El monto disputado ({policy_input.transaction_amount:,.2f} {policy_input.transaction_currency}, ${policy_input.amount_usd:,.2f} USD equiv.) supera el límite de resolución automática ($500 USD). Un especialista revisará el caso.",
                f"O valor contestado ({policy_input.transaction_amount:,.2f} {policy_input.transaction_currency}, ${policy_input.amount_usd:,.2f} USD equiv.) excede o limite de resolução automática ($500 USD). Um especialista revisará o caso.",
            ))
        if policy_input.ml_risk_score > policy_input.ml_risk_threshold:
            fired.append((
                "POL-ESC-ML-RISK", "HIGH_FRAUD_RISK_SCORE",
                "Detectamos señales de riesgo en este movimiento. Un especialista del equipo de prevención de fraude revisará su caso con prioridad.",
                "Detectamos sinais de risco neste movimento. Um especialista da equipe de prevenção a fraudes revisará o seu caso com prioridade.",
            ))
        if policy_input.recent_disputed_charges_count > 2:
            fired.append((
                "POL-ESC-MULTI", "MULTIPLE_CHARGES_48H",
                "Se reportaron múltiples cargos no reconocidos en menos de 48 horas. Se activa protocolo de seguridad con escalamiento a especialista.",
                "Foram relatadas múltiplas cobranças não reconhecidas em menos de 48 horas. Protocolo de segurança ativado com transferência para especialista.",
            ))
        if cls._severe_distress(policy_input.customer_distress_score, policy_input.prior_distress_max_30d, msg_lower):
            fired.append((
                "POL-ESC-DISTRESS", "SEVERE_DISTRESS",
                "Queremos atenderle con prioridad. Un especialista tomará su caso de inmediato.",
                "Queremos atendê-lo com prioridade. Um especialista assumirá o seu caso imediatamente.",
            ))
        return fired

    @classmethod
    def message_escalation(cls, message: str, distress_score: float | None = None,
                           prior_distress_max_30d: float | None = None) -> str | None:
        """POL-ESC-LEGAL or POL-ESC-DISTRESS when the message and the case memory alone fire it, before any charge is known.
        The routing into the policy explainer keeps such a turn in the dispute flow (docs/RAG_IMPLEMENTATION_ROADMAP.md, Task 5.1)."""
        msg_lower = message.lower()
        if cls._cites_regulator_or_legal(msg_lower):
            return "POL-ESC-LEGAL"
        if cls._severe_distress(distress_score, prior_distress_max_30d, msg_lower):
            return "POL-ESC-DISTRESS"
        return None

    @classmethod
    def _cites_regulator_or_legal(cls, msg_lower: str) -> bool:
        return any(re.search(pattern, msg_lower) for pattern in cls.REGULATOR_OR_LEGAL_KEYWORDS)

    @staticmethod
    def _severe_distress(score: float | None, prior_distress_max_30d: float | None, msg_lower: str) -> bool:
        if score is not None:
            current = score >= 2.0
        else:
            current = any(k in msg_lower for k in DISTRESS_KEYWORDS)
        remembered = prior_distress_max_30d is not None and prior_distress_max_30d >= 2.0
        return current or remembered

    @classmethod
    def _clarification_reason(cls, policy_input: DisputePolicyInput) -> str | None:
        """POL-CLARIFY conditions in spec order. Candidate counting is skipped for out-of-scope intents (S4)."""
        if policy_input.dispute_intent != "fuera_de_alcance":
            if policy_input.candidate_charges_count == 0:
                return "NO_CANDIDATE_CHARGE"
            if policy_input.candidate_charges_count > 1:
                return "MULTIPLE_CANDIDATE_CHARGES"
        if policy_input.intent_confidence is not None and policy_input.intent_confidence < 0.70:
            return "LOW_INTENT_CONFIDENCE"
        stolen = policy_input.is_stolen_reported
        if stolen is not None and 0.40 <= stolen <= 0.60:
            return "STOLEN_CARD_AMBIGUOUS"
        return None

    @classmethod
    def evaluate(cls, policy_input: DisputePolicyInput) -> DisputePolicyDecision:
        """Apply the clauses in spec order, then attach the outcome-independent parts (POL-AUT-LOCK)."""
        decision = cls._evaluate_outcome(policy_input)
        # POL-AUT-LOCK: a multi-charge claim or a stolen-card claim recommends the lock on any outcome;
        # when both apply the more specific reason (stolen card) names it.
        if policy_input.recent_disputed_charges_count > 2:
            decision.card_lock_recommended = True
            decision.card_lock_reason = "MULTI_CHARGE_FRAUD"
        if cls._stolen_card_claimed(policy_input):
            decision.card_lock_recommended = True
            decision.card_lock_reason = "STOLEN_CARD_CLAIM"
        if decision.card_lock_recommended:
            decision.card_lock_required_authentication = cls.ACTION_AUTH_MATRIX["LOCK_CARD"][1]
        decision.required_authentication = cls.ACTION_AUTH_MATRIX[decision.action_required][1]
        decision.risk_top_features = list(policy_input.risk_top_features)
        decision.case_memory = {
            "prior_distress_max_30d": policy_input.prior_distress_max_30d,
            "prior_escalations_180d": policy_input.prior_escalations_180d,
            "prior_cases_180d": policy_input.prior_cases_180d,
            "prior_lock_refused": policy_input.prior_lock_refused,
        }
        return decision

    @staticmethod
    def _stolen_card_claimed(policy_input: DisputePolicyInput) -> bool:
        """POL-AUT-LOCK: Jev stolen-card probability >= 0.80, or the keyword fallback when Jev is absent."""
        if policy_input.is_stolen_reported is not None:
            return policy_input.is_stolen_reported >= 0.80
        msg_lower = policy_input.customer_message.lower()
        return any(k in msg_lower for k in STOLEN_CARD_KEYWORDS)

    @classmethod
    def _evaluate_outcome(cls, policy_input: DisputePolicyInput) -> DisputePolicyDecision:
        # 1. LEGAL / REGULATOR ESCALATION (POL-ESC-LEGAL): before the window, so it escalates even an old charge
        msg_lower = policy_input.customer_message.lower()
        if cls._cites_regulator_or_legal(msg_lower):
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome=OUTCOME_ESCALATION,
                provisional_credit_candidate=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-ESC-LEGAL"],
                escalation_reason="REGULATOR_OR_LEGAL_CITING",
                action_required=ACTION_ESCALATE,
                explanation_es="Su caso requiere atención prioritaria por parte de un especialista de atención bancaria y cumplimiento.",
                explanation_pt="Seu caso requer atenção prioritária de um especialista em atendimento bancário e conformidade."
            )

        # 2. IDENTIFY THE CHARGE (POL-CLARIFY / POL-ESC-AMBIG)
        clarification_reason = cls._clarification_reason(policy_input)
        if clarification_reason is not None:
            if policy_input.clarification_attempts >= 2:
                return DisputePolicyDecision(
                    is_eligible=False,
                    policy_outcome=OUTCOME_ESCALATION,
                    provisional_credit_candidate=False,
                    provisional_credit_amount_usd=0.0,
                    cited_clauses=["POL-CLARIFY", "POL-ESC-AMBIG"],
                    escalation_reason="UNRESOLVED_AFTER_CLARIFICATIONS",
                    action_required=ACTION_ESCALATE,
                    explanation_es="No logramos identificar el cargo con la información disponible. Un especialista continuará con su caso.",
                    explanation_pt="Não conseguimos identificar a cobrança com as informações disponíveis. Um especialista dará continuidade ao seu caso.",
                )
            es, pt = cls.CLARIFICATION_TEXTS[clarification_reason]
            return DisputePolicyDecision(
                is_eligible=False,
                policy_outcome=OUTCOME_CLARIFICATION,
                provisional_credit_candidate=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-CLARIFY"],
                clarification_reason=clarification_reason,
                action_required=ACTION_ASK,
                explanation_es=es,
                explanation_pt=pt,
            )

        # Past POL-CLARIFY with exactly one candidate the caller must hand over the matched charge.
        if policy_input.dispute_intent != "fuera_de_alcance":
            missing = [name for name in ("transaction_id", "transaction_date", "transaction_amount", "transaction_currency",
                                         "transaction_type", "transaction_status")
                       if getattr(policy_input, name) is None]
            if missing:
                raise ValueError(f"Matched charge is incomplete after POL-CLARIFY: missing {', '.join(missing)}")

        # 3. DISPUTABLE CHARGE (POL-DISP-TYPE), part 1: out-of-scope intent needs no charge
        if policy_input.dispute_intent == "fuera_de_alcance":
            category = policy_input.out_of_scope_category or "no_determinado"
            if category not in OUT_OF_SCOPE_CATEGORIES:
                raise ValueError(f"Unknown out-of-scope category: {category!r}")
            label_es, label_pt = cls.OUT_OF_SCOPE_LABELS[category]
            return cls._abstention(
                policy_input, reason="OUT_OF_SCOPE_INTENT",
                explanation_es=f"Este canal atiende disputas de cargos en sus tarjetas y cuentas. Su consulta sobre {label_es} la atiende la línea de atención o la sección correspondiente de la app.",
                explanation_pt=f"Este canal atende contestações de cobranças em seus cartões e contas. Sua solicitação sobre {label_pt} é atendida pela central de atendimento ou pela seção correspondente do aplicativo.",
            )

        # Days since the bank process day (process_date = date(transaction_date - 6 h)) relative to current_date
        tx_date = (policy_input.transaction_date - timedelta(hours=6)).date() if isinstance(policy_input.transaction_date, datetime) else policy_input.transaction_date
        days_diff = (policy_input.current_date - tx_date).days

        # 3. DISPUTABLE CHARGE (POL-DISP-TYPE), part 2: only Approved debits; data errors abstain or escalate
        if policy_input.transaction_status != DISPUTABLE_STATUS or policy_input.transaction_type not in DISPUTABLE_TYPES:
            return cls._abstention(
                policy_input, reason="NOT_DISPUTABLE_CHARGE",
                explanation_es=f"El movimiento es de tipo {policy_input.transaction_type} en estado {policy_input.transaction_status}, por lo que no puede disputarse por este canal. Solo se disputan compras, pagos, retiros y transferencias aprobadas.",
                explanation_pt=f"O movimento é do tipo {policy_input.transaction_type} com status {policy_input.transaction_status}, portanto não pode ser contestado por este canal. Só são contestáveis compras, pagamentos, saques e transferências aprovadas.",
            )
        if days_diff < 0:
            return cls._abstention(
                policy_input, reason="DATA_ERROR_FUTURE_DATE", data_quality_flag="FUTURE_DATED_CHARGE",
                explanation_es="La fecha del movimiento es posterior a hoy, lo que indica un error en los datos. Lo enviamos a revisión de calidad de datos y no abrimos un caso por ahora.",
                explanation_pt="A data do movimento é posterior a hoje, o que indica um erro nos dados. Enviamos para revisão de qualidade de dados e não abrimos um caso por enquanto.",
            )
        if policy_input.amount_usd is None:
            return DisputePolicyDecision(
                is_eligible=False,
                policy_outcome=OUTCOME_ESCALATION,
                provisional_credit_candidate=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-DISP-TYPE"],
                escalation_reason="DATA_GAP_AMOUNT_USD",
                data_quality_flag="MISSING_AMOUNT_USD",
                action_required=ACTION_ESCALATE,
                explanation_es="No contamos con el equivalente en dólares de este movimiento, así que un especialista revisará su caso.",
                explanation_pt="Não temos o equivalente em dólares deste movimento, portanto um especialista revisará o seu caso.",
            )

        # 4. FILING WINDOW CHECK (POL-WIN-60)
        if days_diff > 60:
            return DisputePolicyDecision(
                is_eligible=False,
                policy_outcome=OUTCOME_ABSTENTION,
                provisional_credit_candidate=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-DISP-TYPE", "POL-WIN-60"],
                escalation_reason="OUT_OF_POLICY_WINDOW",
                action_required=ACTION_ABSTAIN,
                explanation_es=f"La transacción ocurrió hace {days_diff} días, superando el plazo de 60 días para disputas automáticas. Por favor acérquese a una sucursal.",
                explanation_pt=f"A transação ocorreu há {days_diff} dias, excedendo o prazo de 60 dias para contestações automáticas. Por favor, dirija-se a uma agência."
            )

        # 5. MANDATORY HUMAN ESCALATION, in spec order: the first clause decides, the rest are secondary
        fired = cls._escalations(policy_input, msg_lower)
        if fired:
            clause, reason, explanation_es, explanation_pt = fired[0]
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome=OUTCOME_ESCALATION,
                provisional_credit_candidate=False,
                provisional_credit_amount_usd=0.0,
                cited_clauses=["POL-DISP-TYPE", "POL-WIN-60", clause],
                secondary_clauses=[f[0] for f in fired[1:]],
                escalation_reason=reason,
                action_required=ACTION_ESCALATE,
                explanation_es=explanation_es,
                explanation_pt=explanation_pt,
            )

        # 6. PROVISIONAL-CREDIT CANDIDATE (POL-AUT-150): a flag a human approves in the console (rule 8)
        is_tier_eligible = policy_input.customer_segment in ("Premium", "Plus")
        is_mature_account = policy_input.account_age_days > 180
        is_clean_history = policy_input.complaints_last_90d == 0
        is_amount_eligible = policy_input.amount_usd <= 150.0
        if is_amount_eligible and is_tier_eligible and is_mature_account and is_clean_history:
            return DisputePolicyDecision(
                is_eligible=True,
                policy_outcome=OUTCOME_AUTONOMOUS,
                provisional_credit_candidate=True,
                provisional_credit_amount_usd=policy_input.amount_usd,
                cited_clauses=["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE", "POL-AUT-150"],
                action_required=ACTION_OPEN_DISPUTE,
                case_values=cls._case_values(policy_input),
                explanation_es=cls._intake_text_es(policy_input),
                explanation_pt=cls._intake_text_pt(policy_input),
            )

        # 7. AUTONOMOUS INTAKE (POL-AUT-INTAKE): open the case with data-dictionary values
        return DisputePolicyDecision(
            is_eligible=True,
            policy_outcome=OUTCOME_AUTONOMOUS,
            provisional_credit_candidate=False,
            provisional_credit_amount_usd=0.0,
            cited_clauses=["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE"],
            action_required=ACTION_OPEN_DISPUTE,
            case_values=cls._case_values(policy_input),
            explanation_es=cls._intake_text_es(policy_input),
            explanation_pt=cls._intake_text_pt(policy_input),
        )
