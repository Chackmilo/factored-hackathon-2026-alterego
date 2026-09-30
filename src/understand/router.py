"""
The "smart agent" of the Understand stage (team decision TQ-008, 27-Sep): deterministic rules choose, per turn,
which engine reads the customer's message and which one drafts the reply. It routes model calls; it never
decides an outcome or an action (rule 6): the typed signals go to the policy engine as before.

Signals engine: Jev when it is available, the daily budget allows the call, and the message needs a
categorization (not a bare yes, no or option number, not the lock confirmation turn); otherwise the keyword
extractor. If Jev fails mid-call the turn falls back to keywords and the audit records why.

Reply engine: Claude when a key exists and the budget allows, for turns whose template benefits from wording
(clarification questions and escalations); templates otherwise. Claude only fills placeholders with verified
facts; it does not run here yet (no key), so the choice is recorded and the template is used.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.llm.budget import BudgetExceeded, LlmBudget
from src.privacy.pii_masker import PIIMasker
from src.understand.jev_extractor import (
    EngineUnavailable,
    IntentEngine,
    estimate_jev_cost_usd,
    jev_cost_usd,
    merge,
)
from src.understand.keyword_extractor import KeywordIntentExtractor, UnderstandResult

TRIVIAL_MAX_CHARS = 12
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_REPLY_ESTIMATE_USD = 0.002  # about 1,500 input and 200 output tokens of Haiku 4.5


@dataclass
class RoutingDecision:
    signals_engine: str  # "jev" | "keyword"
    reply_engine: str  # "claude" | "template"
    reason: str
    fallback_from: str | None = None
    fallback_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"signals_engine": self.signals_engine, "reply_engine": self.reply_engine, "routing_reason": self.reason,
                "fallback_from": self.fallback_from, "fallback_error": self.fallback_error}


class UnderstandRouter:
    def __init__(self, keyword: KeywordIntentExtractor | None = None, jev: IntentEngine | None = None,
                 budget: LlmBudget | None = None, claude_key: str | None = None):
        self.keyword = keyword or KeywordIntentExtractor()
        self.jev = jev
        self.budget = budget
        self.claude_key = claude_key if claude_key is not None else os.getenv("ANTHROPIC_API_KEY", "")

    # ----------------------------------------------------------- signals engine
    def understand(self, text: str, state: str, history: list[str] | None = None) -> tuple[UnderstandResult, RoutingDecision]:
        trivial = (self._is_trivial(text) or state == "awaiting_lock_confirmation"
                   or (state == "awaiting_clarification" and self.keyword.option_reply(text) is not None))
        if trivial:
            return self._keyword(text, "trivial turn: yes, no, option number or lock confirmation")
        if self.jev is None or not self.jev.available():
            return self._keyword(text, "jev unavailable: no key or SDK")
        if self.budget is not None:
            try:
                self.budget.check(estimate_jev_cost_usd(text, history))
            except BudgetExceeded as exc:
                return self._keyword(text, f"budget: {exc}")
        masked = PIIMasker.sanitize(text).sanitized_text  # Jev sees the masked message only; slots come from the raw text locally
        try:
            signals = self.jev.signals(masked, history)
        except EngineUnavailable as exc:
            keyword_result, decision = self._keyword(text, "jev failed mid-call")
            decision.fallback_from, decision.fallback_error = "jev", str(exc)[:200]
            return keyword_result, decision
        result = merge(self.keyword.extract(text), signals, self.jev.name)
        if self.budget is not None:
            self.budget.record(provider="typesafe", model=signals.model, purpose="signals", tokens_in=signals.tokens_in, tokens_out=signals.tokens_out,
                               cost_usd=jev_cost_usd(signals.tokens_in), request_id=signals.request_id)
        return result, RoutingDecision(signals_engine="jev", reply_engine=self._reply_engine(), reason="jev categorizes the customer's purpose")

    def _keyword(self, text: str, reason: str) -> tuple[UnderstandResult, RoutingDecision]:
        result = self.keyword.extract(text)
        result.engine = "keyword"
        return result, RoutingDecision(signals_engine="keyword", reply_engine=self._reply_engine(), reason=reason)

    # ------------------------------------------------------------- reply engine
    def _reply_engine(self) -> str:
        if not self.claude_key:
            return "template"
        if self.budget is not None:
            try:
                self.budget.check(CLAUDE_REPLY_ESTIMATE_USD)
            except BudgetExceeded:
                return "template"
        return "claude"

    @staticmethod
    def _is_trivial(text: str) -> bool:
        stripped = text.strip().lower()
        return len(stripped) <= TRIVIAL_MAX_CHARS
