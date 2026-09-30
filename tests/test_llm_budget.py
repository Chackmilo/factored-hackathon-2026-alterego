"""Daily model budget (TQ-015): 2 USD per day across providers; over the cap the caller falls back to the offline path."""
from datetime import datetime

import pytest

from src.llm.budget import BudgetExceeded, LlmBudget
from src.ops.store import OpsStore


def test_budget_caps_the_day_at_two_dollars():
    budget = LlmBudget(OpsStore(":memory:"), daily_budget_usd=2.0)
    day = datetime(2026, 9, 27, 10, 0, 0)
    assert budget.check(0.5, now=day) == 2.0 - 0.5
    budget.record(provider="anthropic", model="claude-haiku-4-5-20251001", purpose="reply", tokens_in=1200, tokens_out=300, cost_usd=1.5, now=day)
    budget.record(provider="typesafe", model="jev-1.13.0", purpose="signals", tokens_in=400, tokens_out=0, cost_usd=0.4, now=day)
    assert budget.spent_today(day) == pytest.approx(1.9)
    assert budget.check(0.1, now=day) == pytest.approx(0.0)
    with pytest.raises(BudgetExceeded):
        budget.check(0.2, now=day)
    # a new day starts fresh
    assert budget.spent_today(datetime(2026, 9, 28, 0, 0, 1)) == 0.0


def test_budget_default_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0.5")
    assert LlmBudget(OpsStore(":memory:")).daily_budget_usd == 0.5
    monkeypatch.delenv("LLM_DAILY_BUDGET_USD")
    assert LlmBudget(OpsStore(":memory:")).daily_budget_usd == 2.0
