"""
Daily spend cap for external model keys (team decision TQ-015, 27-Sep: at most 2 USD per day).

Every call to an external model (Claude Haiku for replies, Jev for typed signals) records its usage in
ops_llm_usage and checks the cap first. The cap is per calendar day (UTC) across all providers; a call that
would exceed it raises BudgetExceeded and the caller falls back to templates or the keyword extractor,
which the app runs on anyway. Usage rows are append-only facts for the report (cost per attempted case).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from src.ops.store import OpsStore

DEFAULT_DAILY_BUDGET_USD = 2.0

LLM_USAGE_DDL = """CREATE TABLE IF NOT EXISTS ops_llm_usage (
    usage_id TEXT PRIMARY KEY, conversation_id TEXT, provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, cost_usd DOUBLE NOT NULL DEFAULT 0.0,
    request_id TEXT, created_at TIMESTAMP NOT NULL)"""


class BudgetExceeded(RuntimeError):
    """The daily cap would be exceeded; the caller must use the offline path."""


class LlmBudget:
    def __init__(self, ops: OpsStore, daily_budget_usd: float | None = None):
        self.ops = ops
        self.daily_budget_usd = float(daily_budget_usd if daily_budget_usd is not None else os.getenv("LLM_DAILY_BUDGET_USD", DEFAULT_DAILY_BUDGET_USD))
        if not ops.is_postgres:
            ops._run(LLM_USAGE_DDL)

    def spent_today(self, now: datetime | None = None) -> float:
        now = now or datetime.utcnow()
        start = datetime(now.year, now.month, now.day)
        rows = self.ops._run("SELECT COALESCE(SUM(cost_usd), 0.0) FROM ops_llm_usage WHERE created_at >= ? AND created_at < ?",
                             [start, start + timedelta(days=1)])
        return float(rows[0][0] or 0.0)

    def check(self, estimated_cost_usd: float = 0.0, now: datetime | None = None) -> float:
        """Returns the remaining budget after the estimated call, or raises BudgetExceeded."""
        remaining = self.daily_budget_usd - self.spent_today(now)
        if remaining - estimated_cost_usd < 0:
            raise BudgetExceeded(f"Daily model budget of {self.daily_budget_usd:.2f} USD would be exceeded (remaining {remaining:.4f} USD)")
        return remaining - estimated_cost_usd

    def record(self, *, provider: str, model: str, purpose: str, tokens_in: int, tokens_out: int, cost_usd: float,
               conversation_id: str | None = None, request_id: str | None = None, now: datetime | None = None) -> str:
        from src.ops.store import _new_id

        usage_id = _new_id("USE")
        self.ops._run(
            """INSERT INTO ops_llm_usage (usage_id, conversation_id, provider, model, purpose, tokens_in, tokens_out, cost_usd, request_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [usage_id, conversation_id, provider, model, purpose, int(tokens_in), int(tokens_out), float(cost_usd), request_id, now or datetime.utcnow()],
        )
        return usage_id
