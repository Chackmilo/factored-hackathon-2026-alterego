"""
Jev (TypeSafe AI) adapter behind the same typed contract as the keyword extractor (docs/JEV_TYPESAFE_AI.md).

Jev is System 1: in one call it categorizes the customer's purpose (intent), the stolen-card claim, the
distress level and, for out-of-scope requests, the unsupported category. It never writes text or decides an
action. It sees only the masked message (and the masked earlier messages of the conversation); amounts,
dates and yes/no answers stay with the local keyword extractor. StubJev serves tests and the harness without
a network; FakeJevClient lets tests exercise the real adapter's mapping offline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.understand.keyword_extractor import (
    OUT_OF_SCOPE_KEYWORDS,
    KeywordIntentExtractor,
    UnderstandResult,
)

JEV_MODEL = "jev-1.13.0"  # pinned (docs/PLAN.md row 'Versiones de Jev'); the aliases jev-latest and jev-preview move on their own
JEV_INPUT_USD_PER_MILLION_TOKENS = 0.042

INTENT_CRITERIA = {
    "cargo_no_reconocido": "El cliente no reconoce una transacción o compra en su cuenta o tarjeta.",
    "cobro_indebido": "El cliente reconoce el comercio pero impugna un cobro duplicado, un monto erróneo o un cobro de más.",
    "tarjeta_robada": "El cliente reporta pérdida física, hurto de la tarjeta o fraude masivo en curso.",
    "consulta_general": "Pregunta general sobre saldo, extracto o movimientos, sin disputar un cargo.",
    "fuera_de_alcance": "Créditos, préstamos, inversiones, seguros, PIN o reposición de tarjeta y otras solicitudes que no son una disputa de cargos.",
}
CATEGORY_CRITERIA = {
    "prestamo_o_credito": "Préstamos, créditos, cupos o límites de crédito, financiamiento.",
    "saldo_o_extracto": "Saldos, extractos, estados de cuenta o movimientos.",
    "inversion_o_seguro": "Inversiones, CDT, fondos o seguros.",
    "soporte_de_tarjeta": "PIN, clave, reposición, segunda vía, entrega o activación de la tarjeta.",
    "otro_producto": "Otro producto del banco que no es una tarjeta ni una cuenta con cargos.",
    "no_determinado": "No se puede determinar la categoría.",
}
STOLEN_CRITERIA = {"true": "La tarjeta fue extraviada, clonada con pérdida física o robada.",
                   "false": "El cliente conserva su tarjeta física y solo impugna un cargo remoto o no reconocido."}
DISTRESS_CRITERIA = ["0: Tono neutral, consulta habitual sin urgencia.", "1: Preocupación moderada por la transacción.",
                     "2: Fuerte alteración, afectación de subsistencia o saldo esencial.", "3: Situación de crisis extrema o fraude masivo en curso."]


class EngineUnavailable(RuntimeError):
    """The engine has no key, no network, or returned an error: the router falls back."""


@dataclass
class JevSignals:
    """Typed answers of one Jev call, as the policy consumes them."""
    intent: str
    intent_confidence: float
    stolen_card_probability: float
    distress_score: float
    out_of_scope_category: str | None = None
    request_id: str | None = None
    model: str = JEV_MODEL
    tokens_in: int = 0
    tokens_out: int = 0
    probabilities: dict[str, float] = field(default_factory=dict)


class IntentEngine(Protocol):
    name: str

    def available(self) -> bool: ...
    def signals(self, masked_text: str, history: list[str] | None = None) -> JevSignals: ...


def build_questions():
    import typesafe_sdk as ts

    return {
        "intent": ts.Choice(instructions="Clasifica la intención principal del mensaje del cliente bancario.", criteria=INTENT_CRITERIA),
        "category": ts.Choice(instructions="Si el mensaje no es una disputa de cargos, ¿a qué categoría pertenece? Si es una disputa, responde no_determinado.", criteria=CATEGORY_CRITERIA),
        "stolen_card": ts.Noul(instructions="¿El cliente afirma haber perdido la tarjeta física o sufrido el robo de la tarjeta?", criteria=STOLEN_CRITERIA),
        "distress": ts.Score(instructions="Evalúa el nivel de angustia o vulnerabilidad manifestado por el cliente.", criteria=DISTRESS_CRITERIA),
    }


class JevExtractor:
    """Real client through typesafe-sdk when TYPESAFE_API_KEY is set. State: the masked message and masked history only."""

    name = "jev"

    def __init__(self, api_key: str | None = None, model: str = JEV_MODEL, client: Any = None, include_history: bool = False):
        self.api_key = api_key if api_key is not None else os.getenv("TYPESAFE_API_KEY", "")
        self.model = model
        self._client = client
        # Verified 27-Sep: with the earlier messages in the state, the stolen-card and distress answers followed the
        # previous turn (a loan question inherited stolen 0.91 and distress 2.02 and got a lock offer). The answers must
        # describe the current message, so the history stays out unless explicitly enabled.
        self.include_history = include_history

    def available(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            import typesafe_sdk  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self):
        if self._client is None:
            import typesafe_sdk as ts

            self._client = ts.TypeSafeClient(api_key=self.api_key, model=self.model)
        return self._client

    def signals(self, masked_text: str, history: list[str] | None = None) -> JevSignals:
        if not self.available():
            raise EngineUnavailable("Jev key or SDK missing")
        state: dict[str, Any] = {"message": masked_text}
        if history and self.include_history:
            state["previous_messages"] = list(history)[-5:]
        try:
            response = self._get_client().system_one(state=state, questions=build_questions(), model=self.model)
        except Exception as exc:  # SDK errors (auth, rate limit, timeout, validation) all mean: fall back this turn
            raise EngineUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc
        return self.parse(response)

    @staticmethod
    def parse(response: Any) -> JevSignals:
        intent = response.choices["intent"]
        category = response.choices.get("category") if hasattr(response.choices, "get") else None
        usage = getattr(response, "usage", None)
        chosen = str(intent.choice)
        return JevSignals(
            intent=chosen,
            intent_confidence=float(intent.confidence),
            stolen_card_probability=float(response.nouls["stolen_card"].noul),
            distress_score=float(response.scores["distress"].score),
            out_of_scope_category=(str(category.choice) if (category is not None and chosen == "fuera_de_alcance") else None),
            request_id=getattr(response, "request_id", None),
            model=str(getattr(response, "model", JEV_MODEL)),
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
            probabilities={str(k): float(v) for k, v in (intent.probabilities or {}).items()},
        )


@dataclass
class StubJev:
    """Deterministic stand-in: fixed answers by exact message, else the keyword reading with a fixed confidence."""
    answers: dict[str, JevSignals] = field(default_factory=dict)
    default_confidence: float = 0.9
    name: str = "jev-stub"
    calls: int = 0
    fail: bool = False

    def available(self) -> bool:
        return not self.fail

    def signals(self, masked_text: str, history: list[str] | None = None) -> JevSignals:
        if self.fail:
            raise EngineUnavailable("stub configured to fail")
        self.calls += 1
        if masked_text in self.answers:
            return self.answers[masked_text]
        base = KeywordIntentExtractor().extract(masked_text)
        return JevSignals(intent=base.intent, intent_confidence=self.default_confidence,
                          stolen_card_probability=0.95 if base.stolen_card_claimed else 0.05, distress_score=0.2,
                          out_of_scope_category=base.out_of_scope_category, model="jev-stub")


def merge(base: UnderstandResult, signals: JevSignals, engine: str) -> UnderstandResult:
    """Combine the local slots (amount, date, yes/no, option) with Jev's typed categorization."""
    base.intent = signals.intent
    base.intent_confidence = signals.intent_confidence
    base.out_of_scope_category = signals.out_of_scope_category if signals.intent == "fuera_de_alcance" else None
    if signals.intent == "fuera_de_alcance" and base.out_of_scope_category is None:
        base.out_of_scope_category = next((cat for cat, words in OUT_OF_SCOPE_KEYWORDS.items() if any(w in base.message_lower for w in words)), "no_determinado")
    base.stolen_card_probability = signals.stolen_card_probability
    base.distress_score = signals.distress_score
    base.engine = engine
    base.request_id = signals.request_id
    base.model = signals.model
    base.tokens_in = signals.tokens_in
    return base


def jev_cost_usd(tokens_in: int) -> float:
    return tokens_in / 1_000_000 * JEV_INPUT_USD_PER_MILLION_TOKENS


def estimate_jev_cost_usd(text: str, history: list[str] | None = None) -> float:
    chars = len(text) + sum(len(h) for h in (history or [])) + 700 * 4  # the questions themselves are about 700 tokens
    return jev_cost_usd(int(chars / 4))
