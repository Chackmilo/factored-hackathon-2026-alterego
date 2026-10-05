"""
Hypothesis 4 (docs/PLAN.md): does Jev read the customer's message better than the keyword extractor, and is it calibrated
in Spanish and in Portuguese? Measured on a bank of labeled customer messages, with a mix of both engines beside them.

    uv run python -m src.eval.intent_benchmark --out reports/intent_benchmark          # keyword extractor alone, no network
    uv run python -m src.eval.intent_benchmark --out reports/intent_benchmark --jev    # real, billed Jev calls (TYPESAFE_API_KEY)

A bank row (JSONL): message_id, language (es or pt), text, expected_topics (any of disputa, tarjeta, reglas, or
fuera:<category>) and provenance. A message is read right when the engine names exactly its set of labels. The test split
is frozen by <test>.sha256. The decision rules are in reports/intent_hypothesis4_report.md and were committed before any
engine read the test split.

The mix calls Jev only when the keyword reading is not sure of itself: it found no topic, or it guessed the dispute from a
charge word or an amount without a dispute phrase. Two rules are compared on the development split ("gate": Jev's reading
stands; "gate_union": a topic counts if either engine names it) and the better one is the one reported on the test split.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.eval.intervals import mcnemar_exact, wilson_interval
from src.privacy.pii_masker import PIIMasker
from src.understand.jev_extractor import estimate_jev_cost_usd, jev_cost_usd, merge
from src.understand.keyword_extractor import INTENT_KEYWORDS, KeywordIntentExtractor
from src.understand.topics import CARD_TOPIC, DISPUTE_TOPICS, OUT_OF_SCOPE_TOPICS, RULES_TOPIC

DEFAULT_DEV = Path("data/eval/intent_messages_dev.jsonl")
DEFAULT_TEST = Path("data/eval/intent_messages_test.jsonl")
LABELS = ("disputa", "tarjeta", "reglas", "fuera")
MIX_RULES = ("gate", "gate_union")
QUESTIONS = {"dispute": "disputa", "stolen_card": "tarjeta", "other_request": "fuera"}  # Jev's yes or no answers and the label each one claims
_DISPUTE_PHRASES = frozenset(w for words in INTENT_KEYWORDS.values() for w in words)


@dataclass(frozen=True)
class Message:
    message_id: str
    language: str
    text: str
    labels: frozenset[str]
    category: str | None
    provenance: str


@dataclass(frozen=True)
class Reading:
    labels: frozenset[str]
    category: str | None
    sure: bool = True  # the keyword reading's own doubt; a Jev reading leaves it True
    probabilities: dict[str, float] | None = None


def labels_of(topics: list[str]) -> tuple[frozenset[str], str | None]:
    """The topics of src/understand/topics.py as the four labels of the bank, plus the category of the other request."""
    labels = set()
    if CARD_TOPIC in topics:
        labels.add("tarjeta")
    if any(t in DISPUTE_TOPICS for t in topics):
        labels.add("disputa")
    if RULES_TOPIC in topics:
        labels.add("reglas")
    category = next((t for t in topics if t in OUT_OF_SCOPE_TOPICS), None)
    if category:
        labels.add("fuera")
    return frozenset(labels), category


def load_messages(path: str | Path) -> list[Message]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        labels, category = set(), None
        for topic in row["expected_topics"]:
            name, _, cat = topic.partition(":")
            if name not in LABELS or (name == "fuera") != bool(cat) or (cat and cat not in OUT_OF_SCOPE_TOPICS):
                raise ValueError(f"{row['message_id']}: unknown label {topic!r}")
            labels.add(name)
            category = cat or category
        if row["language"] not in ("es", "pt"):
            raise ValueError(f"{row['message_id']}: unknown language {row['language']!r}")
        out.append(Message(row["message_id"], row["language"], row["text"], frozenset(labels), category, row["provenance"]))
    return out


def keyword_reading(text: str) -> Reading:
    result = KeywordIntentExtractor().extract(text)
    labels, category = labels_of(result.topics)
    guessed_dispute = "disputa" in labels and not any(k in _DISPUTE_PHRASES for k in result.matched_keywords)
    return Reading(labels, category, sure=bool(labels) and not guessed_dispute)


def jev_reading(jev: Any, text: str) -> tuple[Reading, int]:
    """What the app would understand with Jev: the masked message goes to Jev, the keyword slots stay local. Returns the tokens billed."""
    signals = jev.signals(PIIMasker.sanitize(text).sanitized_text)
    labels, category = labels_of(merge(KeywordIntentExtractor().extract(text), signals, getattr(jev, "name", "jev")).topics)
    probabilities = None
    if signals.dispute_probability is not None:
        probabilities = {"dispute": signals.dispute_probability, "stolen_card": signals.stolen_card_probability,
                         "other_request": signals.other_request_probability}
    return Reading(labels, category, probabilities=probabilities), signals.tokens_in


def mix(keyword: Reading, jev: Reading, rule: str) -> tuple[frozenset[str], str | None, bool]:
    """(labels, category, whether Jev was needed). Jev is called only when the keyword reading is not sure of itself."""
    if rule not in MIX_RULES:
        raise ValueError(f"unknown mix rule {rule!r}")
    if keyword.sure:
        return keyword.labels, keyword.category, False
    if rule == "gate":
        return jev.labels, jev.category, True
    return keyword.labels | jev.labels, jev.category or keyword.category, True


def _ratio(num: int, den: int) -> dict[str, Any]:
    lo, hi = wilson_interval(num, den)
    return {"numerator": num, "denominator": den, "rate": (num / den) if den else None, "ci95": [lo, hi]}


def score(expected: list[frozenset[str]], got: list[frozenset[str]]) -> dict[str, Any]:
    labels = {name: {"tp": sum(name in e and name in g for e, g in zip(expected, got)),
                     "fp": sum(name not in e and name in g for e, g in zip(expected, got)),
                     "fn": sum(name in e and name not in g for e, g in zip(expected, got))} for name in LABELS}
    return {"exact": _ratio(sum(e == g for e, g in zip(expected, got)), len(expected)), "labels": labels}


def calibration(probabilities: list[float], truth: list[bool], bins: int = 5) -> dict[str, Any]:
    """Brier score and expected calibration error over equal-width bins of the predicted probability."""
    n = len(probabilities)
    if n == 0:
        return {"n": 0, "brier": None, "ece": None}
    brier = sum((p - float(y)) ** 2 for p, y in zip(probabilities, truth)) / n
    ece = 0.0
    for b in range(bins):
        members = [(p, y) for p, y in zip(probabilities, truth) if (b / bins <= p < (b + 1) / bins) or (b == bins - 1 and p == 1.0)]
        if members:
            ece += len(members) / n * abs(sum(p for p, _ in members) / len(members) - sum(y for _, y in members) / len(members))
    return {"n": n, "brier": brier, "ece": ece}


def _by_language(messages: list[Message], got: list[frozenset[str]]) -> dict[str, Any]:
    out = {}
    for lang in ("es", "pt", "all"):
        idx = [i for i, m in enumerate(messages) if lang in ("all", m.language)]
        out[lang] = score([messages[i].labels for i in idx], [got[i] for i in idx])
    return out


def measure(messages: list[Message], jev: Any = None, budget: Any = None) -> dict[str, Any]:
    keyword = [keyword_reading(m.text) for m in messages]
    block: dict[str, Any] = {"engines": {"keyword": _by_language(messages, [k.labels for k in keyword])},
                             "messages": [{"message_id": m.message_id, "language": m.language, "expected": sorted(m.labels),
                                           "keyword": sorted(k.labels), "keyword_sure": k.sure} for m, k in zip(messages, keyword)]}
    if jev is None:
        return block
    readings = []
    for m in messages:
        if budget is not None:
            budget.check(estimate_jev_cost_usd(m.text))
        reading, tokens_in = jev_reading(jev, m.text)
        if budget is not None:
            budget.record(provider="typesafe", model=getattr(jev, "model", "jev"), purpose="intent_benchmark", tokens_in=tokens_in, tokens_out=0,
                          cost_usd=jev_cost_usd(tokens_in))
        readings.append(reading)
    block["engines"]["jev"] = _by_language(messages, [r.labels for r in readings])
    for rule in MIX_RULES:
        mixed = [mix(k, r, rule) for k, r in zip(keyword, readings)]
        block["engines"][rule] = {**_by_language(messages, [m[0] for m in mixed]), "jev_calls": sum(m[2] for m in mixed),
                                  "jev_call_share": sum(m[2] for m in mixed) / len(messages)}
    kw_right = [k.labels == m.labels for k, m in zip(keyword, messages)]
    jev_right = [r.labels == m.labels for r, m in zip(readings, messages)]
    only_kw, only_jev = sum(a and not b for a, b in zip(kw_right, jev_right)), sum(b and not a for a, b in zip(kw_right, jev_right))
    block["keyword_vs_jev"] = {"only_keyword": only_kw, "only_jev": only_jev, "p_value": mcnemar_exact(only_kw, only_jev)}
    block["calibration"] = {}
    for lang in ("es", "pt", "all"):
        idx = [i for i, m in enumerate(messages) if lang in ("all", m.language) and readings[i].probabilities]
        block["calibration"][lang] = {q: calibration([readings[i].probabilities[q] for i in idx], [label in messages[i].labels for i in idx])
                                      for q, label in QUESTIONS.items()}
    both_other = [(m, r) for m, r in zip(messages, readings) if m.category and r.category]
    block["jev_category"] = _ratio(sum(m.category == r.category for m, r in both_other), len(both_other))
    for row, r in zip(block["messages"], readings):
        row["jev"] = sorted(r.labels)
        row["jev_probabilities"] = r.probabilities
    return block


def _check_frozen(test_path: Path) -> str:
    recorded = test_path.with_suffix(".sha256")
    if not recorded.exists():
        return "not frozen"
    if recorded.read_text(encoding="utf-8").split()[0] != hashlib.sha256(test_path.read_bytes()).hexdigest():
        raise ValueError(f"{test_path} no longer matches {recorded.name}: the frozen test split changed")
    return "matches its SHA-256"


def run(dev_path: str | Path, test_path: str | Path, out_prefix: str | Path, jev: Any = None, budget: Any = None,
        frozen_check: bool = True) -> dict[str, Any]:
    frozen = _check_frozen(Path(test_path)) if frozen_check else "not checked"
    dev, test = load_messages(dev_path), load_messages(test_path)
    payload: dict[str, Any] = {"dev": measure(dev, jev, budget), "test": measure(test, jev, budget), "chosen_mix": None}
    if jev is not None:  # the mix is chosen on the development split only: most messages right, then fewer Jev calls
        engines = payload["dev"]["engines"]
        payload["chosen_mix"] = max(MIX_RULES, key=lambda r: (engines[r]["all"]["exact"]["numerator"], -engines[r]["jev_calls"]))
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or "unknown"
    except OSError:
        commit = "unknown"
    payload["meta"] = {"commit": commit, "dev": {"path": str(dev_path), "messages": len(dev)},
                       "test": {"path": str(test_path), "messages": len(test), "frozen": frozen},
                       "jev": (f"{getattr(jev, 'name', 'jev')} {getattr(jev, 'model', '')}".strip() if jev is not None else None),
                       "llm_spend_usd": round(budget.spent_today(), 6) if budget is not None else None,
                       "provenance": ", ".join(sorted({m.provenance for m in dev + test}))}
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    return payload


def _fmt(r: dict[str, Any]) -> str:
    if not r["denominator"]:
        return "not defined (0 of 0)"
    return f"{r['rate'] * 100:.1f} % ({r['numerator']} of {r['denominator']})"


def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    lines = ["# Intent benchmark: keyword extractor, Jev and a mix of both", "",
             f"Development split `{meta['dev']['path']}` ({meta['dev']['messages']} messages); test split `{meta['test']['path']}` "
             f"({meta['test']['messages']} messages, {meta['test']['frozen']}). Provenance: {meta['provenance']}. Commit {meta['commit']}. "
             + (f"Jev: {meta['jev']}; spend {meta['llm_spend_usd']} USD. " if meta["jev"] else "Keyword extractor only. ")
             + "A message is read right when the engine names exactly its set of labels. Offline results on the stated provenance."]
    for split in ("dev", "test"):
        block = payload[split]
        lines += ["", f"## {'Development' if split == 'dev' else 'Test'} split", "", "| Engine | Spanish | Portuguese | All | Jev calls |", "| --- | --- | --- | --- | --- |"]
        for name, e in block["engines"].items():
            calls = "none" if name == "keyword" else ("every message" if name == "jev" else f"{e['jev_calls']} ({e['jev_call_share'] * 100:.0f} %)")
            lines.append(f"| {name} | {_fmt(e['es']['exact'])} | {_fmt(e['pt']['exact'])} | {_fmt(e['all']['exact'])} | {calls} |")
        if "keyword_vs_jev" in block:
            v = block["keyword_vs_jev"]
            lines += ["", f"Paired, keyword against Jev: {v['only_keyword']} messages only the keywords read right, {v['only_jev']} only Jev; "
                          f"exact McNemar p {v['p_value']:.4f}. Jev's category of the other request: {_fmt(block['jev_category'])}.", "",
                      "| Label | Engine | Found | Missed | Wrongly named |", "| --- | --- | --- | --- | --- |"]
            for label in LABELS:
                for name in ("keyword", "jev"):
                    c = block["engines"][name]["all"]["labels"][label]
                    lines.append(f"| {label} | {name} | {c['tp']} | {c['fn']} | {c['fp']} |")
            lines += ["", "Calibration of Jev's yes or no answers (Brier score; expected calibration error over five bins):", "",
                      "| Answer | Spanish | Portuguese |", "| --- | --- | --- |"]
            for q in QUESTIONS:
                cells = []
                for lang in ("es", "pt"):
                    c = block["calibration"][lang][q]
                    cells.append("not defined" if c["brier"] is None else f"Brier {c['brier']:.3f}, ECE {c['ece']:.3f} (n {c['n']})")
                lines.append(f"| {q} | {cells[0]} | {cells[1]} |")
    if payload["chosen_mix"]:
        lines += ["", f"Mix chosen on the development split: `{payload['chosen_mix']}`."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Keyword extractor, Jev and a mix of both on the bank of customer messages (Hypothesis 4)")
    parser.add_argument("--dev", default=str(DEFAULT_DEV))
    parser.add_argument("--test", default=str(DEFAULT_TEST))
    parser.add_argument("--out", default="reports/intent_benchmark")
    parser.add_argument("--jev", action="store_true", help="real, billed Jev calls with TYPESAFE_API_KEY, capped by --jev-budget")
    parser.add_argument("--jev-budget", type=float, default=0.10, metavar="USD")
    args = parser.parse_args()
    jev = budget = None
    if args.jev:
        from src.llm.budget import LlmBudget
        from src.ops.store import OpsStore
        from src.understand.jev_extractor import JevExtractor

        jev = JevExtractor()
        if not jev.available():
            raise RuntimeError("TYPESAFE_API_KEY or typesafe-sdk missing: a --jev run needs both")
        budget = LlmBudget(OpsStore(":memory:"), daily_budget_usd=args.jev_budget)
    payload = run(args.dev, args.test, args.out, jev=jev, budget=budget)
    for name, e in payload["test"]["engines"].items():
        print(f"{name}: test {_fmt(e['all']['exact'])}")
    print(f"wrote {args.out}.md and {args.out}.json")


if __name__ == "__main__":
    main()
