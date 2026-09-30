"""
Labeling kit for the held-out suite (TQ-018; decision log row "Suite de evaluación"): the four team members label
independently, 50 cases are labeled twice for Cohen's kappa, and nobody sees the design labels or any system output.

    uv run python -m src.eval.labeling export --suite data/eval/heldout_cases.jsonl --out data/eval/labeling
    uv run python -m src.eval.labeling kappa --labels data/eval/labeling --suite data/eval/heldout_cases.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

MEMBERS = ("A", "B", "C", "D")
PAIRS = [("A", "B"), ("C", "D"), ("A", "C"), ("B", "D"), ("A", "D"), ("B", "C")]
DOUBLE = 50
SEED = 20260930
CASE_FIELDS = ["case_id", "category", "language", "customer", "disputed_charge", "other_charges", "scenario", "messages"]
LABEL_FIELDS = ["final_outcome", "escalation_reason", "requires_human", "case_opened", "credit_candidate", "lock_status",
                "reply_language", "comment"]
YES = {"yes", "y", "true", "1", "si", "sí", "sim"}


def load(suite: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(suite).read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


def _charge(t: dict[str, Any]) -> str:
    return (f"{t['process_date']} {t['amount']} {t['currency']} (USD {t['amount_usd']}), {t['transaction_type']} {t['transaction_status']}, "
            f"merchant {t.get('merchant_name') or 'none'}")


def describe(case: dict[str, Any]) -> dict[str, str]:
    """What a labeler needs to decide, and nothing that states the expected outcome."""
    c = case["customer"]
    target_id = case.get("target_transaction_id")
    target = next((t for t in case["transactions"] if t["transaction_id"] == target_id), None)
    others = [t for t in case["transactions"] if t["transaction_id"] != target_id]
    scenario = []
    if case.get("attack"):
        scenario.append(f"attack {case['attack']['kind']}: {case['attack']['variant']}")
    if case.get("fault"):
        scenario.append(f"fault: {case['fault']['target']}.{case['fault']['method']} {case['fault']['mode']}")
    if not case.get("customer_in_system_of_record", True):
        scenario.append("customer missing from the system of record")
    return {"case_id": case["case_id"], "category": case["category"], "language": case["language"],
            "customer": f"{c['segment']}, {c['country']}, account {c['account_age_days']} days, {c['complaints_last_90d']} complaints in 90 days",
            "disputed_charge": _charge(target) if target else "none",
            "other_charges": " | ".join(f"{t['customer_id'] if t['customer_id'] != c['customer_id'] else 'own'}: {_charge(t)}" for t in others),
            "scenario": "; ".join(scenario) or "none", "messages": " || ".join(case["messages"])}


def assign(case_ids: list[str], seed: int = SEED) -> dict[str, list[str]]:
    """Fifty cases go to a rotating pair of members, the other 200 to one member each: 75 cases per member."""
    ids = sorted(case_ids)
    random.Random(seed).shuffle(ids)
    sheets: dict[str, list[str]] = defaultdict(list)
    for i, cid in enumerate(ids[:DOUBLE]):
        for member in PAIRS[i % len(PAIRS)]:
            sheets[member].append(cid)
    for i, cid in enumerate(ids[DOUBLE:]):
        sheets[MEMBERS[i % len(MEMBERS)]].append(cid)
    return {m: sorted(sheets[m]) for m in MEMBERS}


def export(suite: str | Path, out_dir: str | Path, seed: int = SEED) -> dict[str, Path]:
    cases = {c["case_id"]: c for c in load(suite)}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    for member, ids in assign(list(cases), seed).items():
        path = out / f"labels_{member}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CASE_FIELDS + LABEL_FIELDS)
            writer.writeheader()
            for cid in ids:
                writer.writerow({**describe(cases[cid]), **{field: "" for field in LABEL_FIELDS}})
        written[member] = path
    return written


def cohen_kappa(first: list[str] | tuple[str, ...], second: list[str] | tuple[str, ...]) -> float:
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / n
    c1, c2 = Counter(first), Counter(second)
    expected = sum(c1[k] * c2[k] for k in c1) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def _norm(field: str, value: str) -> str:
    value = (value or "").strip()
    if field in ("requires_human", "case_opened", "credit_candidate") and value:
        return "yes" if value.lower() in YES else "no"
    return value.upper() if field in ("final_outcome", "escalation_reason") else value.lower()


def kappa_report(label_dir: str | Path, suite: str | Path) -> dict[str, Any]:
    """Kappa on the double-labeled cases, and how often a human label agrees with the design label."""
    labels: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for path in sorted(Path(label_dir).glob("labels_*.csv")):
        member = path.stem.split("_", 1)[1]
        for row in csv.DictReader(path.open(encoding="utf-8")):
            labels[row["case_id"]][member] = row
    doubles = [list(rows.values()) for rows in labels.values() if len(rows) == 2]
    fields = {}
    for field in ("final_outcome", "requires_human", "escalation_reason"):
        pairs = [(_norm(field, a[field]), _norm(field, b[field])) for a, b in doubles if a[field].strip() and b[field].strip()]
        if pairs:
            first, second = zip(*pairs)
            fields[field] = {"n": len(pairs), "agreement": sum(x == y for x, y in pairs) / len(pairs), "kappa": cohen_kappa(first, second)}
    design = {c["case_id"]: c["expected"].get("final_outcome") for c in load(suite)}
    human = [(cid, _norm("final_outcome", row["final_outcome"])) for cid, rows in labels.items() for row in rows.values()
             if row["final_outcome"].strip()]
    agree = sum(label == (design.get(cid) or "").upper() for cid, label in human)
    return {"double_labeled": len(doubles), "fields": fields,
            "design_agreement": {"n": len(human), "rate": agree / len(human) if human else None}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Labeling kit of the held-out suite.")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write one blank sheet per member")
    ex.add_argument("--suite", default="data/eval/heldout_cases.jsonl")
    ex.add_argument("--out", default="data/eval/labeling")
    kp = sub.add_parser("kappa", help="Cohen's kappa on the double-labeled cases")
    kp.add_argument("--labels", default="data/eval/labeling")
    kp.add_argument("--suite", default="data/eval/heldout_cases.jsonl")
    args = parser.parse_args()
    if args.command == "export":
        for member, path in export(args.suite, args.out).items():
            print(f"{member}: {path}")
    else:
        print(json.dumps(kappa_report(args.labels, args.suite), indent=2))


if __name__ == "__main__":
    main()
