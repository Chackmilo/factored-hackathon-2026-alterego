"""Official metrics of the brief (section 5) as counts over denominators, with slices."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

from src.eval.cases import EvalCase
from src.eval.runner import CaseResult


def _ratio(num: int, den: int) -> dict[str, Any]:
    return {"numerator": num, "denominator": den, "rate": (num / den) if den else None}


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def in_scope(case: EvalCase) -> bool:
    """TQ-034: a dispute conversation, so neither an out-of-scope request nor an API attack."""
    return case.attack is None and case.expected.get("escalation_reason") != "OUT_OF_SCOPE_INTENT"


def compute_metrics(cases: list[EvalCase], results: list[CaseResult]) -> dict[str, Any]:
    by_id = {c.case_id: c for c in cases}
    n = len(results)
    eligible = [r for r in results if by_id[r.case_id].expected.get("final_outcome") == "AUTONOMOUS_RESOLUTION"]
    scoped = [r for r in results if in_scope(by_id[r.case_id])]
    requires_human = [r for r in results if by_id[r.case_id].expected.get("requires_human")]
    escalated = [r for r in results if r.escalated]
    correct_escalations = [r for r in escalated if by_id[r.case_id].expected.get("requires_human")]
    unsafe = [r for r in results if r.unsafe_reasons]
    unsafe_reasons = Counter(reason for r in results for reason in r.unsafe_reasons)
    latencies = [r.latency_ms for r in results]

    def slice_by(key_fn):
        buckets: dict[str, list[CaseResult]] = defaultdict(list)
        for r in results:
            buckets[str(key_fn(by_id[r.case_id]))].append(r)
        out = {}
        for name, rows in sorted(buckets.items()):
            elig = [r for r in rows if by_id[r.case_id].expected.get("final_outcome") == "AUTONOMOUS_RESOLUTION"]
            out[name] = {"n": len(rows), "safe_automated_resolution": _ratio(sum(r.safe_resolution for r in elig), len(elig)),
                         "unsafe_outcomes": _ratio(sum(1 for r in rows if r.unsafe_reasons), len(rows)),
                         "outcome_accuracy": _ratio(sum(r.checks.get("outcome", False) for r in rows), len(rows))}
        return out

    return {
        "n_cases": n,
        "safe_automated_resolution": _ratio(sum(r.safe_resolution for r in eligible), len(eligible)),
        "safe_automated_resolution_in_scope": _ratio(sum(r.safe_resolution for r in scoped), len(scoped)),
        "attempted_automation_share": _ratio(sum(1 for r in results if r.final_outcome == "AUTONOMOUS_RESOLUTION"), n),
        "containment": _ratio(sum(1 for r in results if not r.escalated), n),
        "escalation_precision": _ratio(len(correct_escalations), len(escalated)),
        "escalation_recall": _ratio(len(correct_escalations), len(requires_human)),
        "missed_transfers": sum(1 for r in requires_human if not r.escalated),
        "unnecessary_transfers": len(escalated) - len(correct_escalations),
        "unsafe_outcomes": _ratio(len(unsafe), n),
        "unsafe_reasons": dict(unsafe_reasons),
        "outcome_accuracy": _ratio(sum(r.checks.get("outcome", False) for r in results), n),
        "reply_language_accuracy": _ratio(sum(r.checks.get("reply_language", False) for r in results if "reply_language" in r.checks),
                                          sum(1 for r in results if "reply_language" in r.checks)),
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95), "mean": statistics.fmean(latencies) if latencies else None},
        "crashes": sum(1 for r in results if r.error),
        "slices": {"language": slice_by(lambda c: c.language), "segment": slice_by(lambda c: c.customer.get("segment")),
                   "country": slice_by(lambda c: c.customer.get("country"))},
    }
