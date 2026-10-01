"""Case format of the development and held-out suites (JSONL, one case per line)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CATEGORIES = {
    "normal_le_150", "normal_150_500", "ambiguous", "out_of_window_or_unsupported", "high_value_or_multi_charge",
    "high_fraud_anomaly", "adversarial_or_security", "tool_or_db_failure", "incorrect_or_missing_data", "multilingual_ambiguity",
}
# Security cases that run through the HTTP API, and faults injected into one method of the ops store or the gateway.
ATTACKS = {"token": {"missing", "hs256", "alg_none", "other_issuer", "expired", "tampered"},
           "cross_customer": {"read_conversation", "post_message"}}
FAULT_TARGETS = {"ops", "gateway"}
FAULT_MODES = {"missing", "verification_error", "timeout"}


@dataclass
class EvalCase:
    case_id: str
    provenance: str
    language: str
    category: str
    customer: dict[str, Any]
    messages: list[str]
    expected: dict[str, Any]
    cards: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    customer_in_system_of_record: bool = True
    notes: str = ""
    attack: dict[str, Any] | None = None  # {"kind", "variant"[, "victim"]}: run through the API instead of the orchestrator
    fault: dict[str, Any] | None = None  # {"target", "method", "mode"}: one method of the ops store or the gateway fails
    label_source: str = "team"  # "design" until the team's labels replace the expectation
    target_transaction_id: str | None = None  # the charge the conversation disputes, for labelers and the suite checks

    @property
    def customer_id(self) -> str:
        return self.customer["customer_id"]


def load_cases(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        raw = json.loads(line)
        if raw["category"] not in CATEGORIES:
            raise ValueError(f"{path}:{line_no}: unknown category {raw['category']!r}")
        if raw["language"] not in ("es", "pt"):
            raise ValueError(f"{path}:{line_no}: language must be es or pt")
        attack = raw.get("attack")
        if attack and attack.get("variant") not in ATTACKS.get(attack.get("kind"), set()):
            raise ValueError(f"{path}:{line_no}: unknown attack {attack!r}")
        fault = raw.get("fault")
        if fault and (fault.get("target") not in FAULT_TARGETS or fault.get("mode") not in FAULT_MODES or not fault.get("method")):
            raise ValueError(f"{path}:{line_no}: unknown fault {fault!r}")
        cases.append(EvalCase(**raw))
    ids = [c.case_id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return cases
