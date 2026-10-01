"""
Benchmark of the policy explainer (docs/RAG_IMPLEMENTATION_ROADMAP.md, Task 4.1): retrieval and gate metrics on the
team's bank of policy questions, with the gate thresholds calibrated on the development split only.

    uv run python -m src.eval.rag_benchmark --out reports/rag_benchmark
    uv run python -m src.eval.rag_benchmark --out reports/rag_benchmark --e5 models/e5-small   # E5 beside BM25 (Task 2.3)
    uv run python -m src.eval.rag_benchmark --out reports/rag_benchmark --write-gate data/rag_gate.json

A bank row (JSONL, Task 1.2): question_id, language (es or pt), text, expected_action (answer, clarify or abstain),
expected_clause_ids (the clauses a right answer cites, or the topics a clarification offers; empty for an abstention) and
provenance. A redirect (an internal clause, TQ-037) counts as an answer that cites the retrieved clause. The test split is
measured once, with the thresholds the development split chose; when <test>.sha256 exists the test file must match it.
Writing the gate file turns the explainer on at the next start (src/rag/policy_explainer.py, load_policy_explainer).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.eval.metrics import _percentile, _ratio
from src.eval.report import _fmt
from src.rag.bm25_retriever import BM25Retriever, Hit
from src.rag.corpus import DEFAULT_CORPUS_PATH, PolicyCorpus, load_corpus
from src.rag.gate import ConfidenceGate
from src.rag.onnx_retriever import MODEL_REPO, MODEL_REVISION, E5Retriever, OnnxE5Embedder
from src.rag.policy_explainer import PolicyExplainer

DEFAULT_DEV = Path("data/eval/policy_questions_dev.jsonl")
DEFAULT_TEST = Path("data/eval/policy_questions_test.jsonl")
FIELDS = ("question_id", "language", "text", "expected_action", "expected_clause_ids", "provenance")
ACTIONS = ("answer", "clarify", "abstain")
LANGUAGES = ("es", "pt")


@dataclass(frozen=True)
class PolicyQuestion:
    question_id: str
    language: str
    text: str
    expected_action: str
    expected_clause_ids: tuple[str, ...]
    provenance: str


def load_questions(path: str | Path, corpus: PolicyCorpus) -> list[PolicyQuestion]:
    clause_ids = {c.clause_id for c in corpus.clauses}
    questions: list[PolicyQuestion] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        data = json.loads(line)
        missing = [f for f in FIELDS if f not in data]
        if missing:
            raise ValueError(f"{path}: {data.get('question_id', '?')}: missing {', '.join(missing)}")
        q = PolicyQuestion(*(data[f] for f in FIELDS[:4]), tuple(data["expected_clause_ids"]), data["provenance"])
        problem = ("a repeated question_id" if any(p.question_id == q.question_id for p in questions)
                   else f"language {q.language!r}" if q.language not in LANGUAGES
                   else f"expected_action {q.expected_action!r}" if q.expected_action not in ACTIONS
                   else "an abstention that names clauses" if q.expected_action == "abstain" and q.expected_clause_ids
                   else f"an expected {q.expected_action} with no clause" if q.expected_action != "abstain" and not q.expected_clause_ids
                   else f"unknown clauses {sorted(set(q.expected_clause_ids) - clause_ids)}" if set(q.expected_clause_ids) - clause_ids
                   else None)
        if problem:
            raise ValueError(f"{path}: {q.question_id}: {problem}")
        questions.append(q)
    return questions


class _Replay:
    """The retriever's hits, computed once per question, so calibration can replay them under every candidate gate."""

    def __init__(self, retriever):
        self.retriever, self._hits = retriever, {}

    def search(self, text: str, k: int = 3) -> list[Hit]:
        if (text, k) not in self._hits:
            self._hits[(text, k)] = self.retriever.search(text, k=k)
        return self._hits[(text, k)]


def _outcome(explainer: PolicyExplainer, q: PolicyQuestion) -> tuple[str, str | None]:
    """The explainer's action as the bank labels it (a redirect is an answer) and the clause it answered with."""
    explanation = explainer.explain(q.text, q.language)
    if explanation.action in ("answer", "redirect"):
        return "answer", explanation.hits[0].clause_id
    return explanation.action, None


def _is_correct(q: PolicyQuestion, action: str, clause: str | None) -> bool:
    return action == q.expected_action and (action != "answer" or clause in q.expected_clause_ids)


def calibrate(questions: list[PolicyQuestion], corpus: PolicyCorpus, retriever) -> ConfidenceGate:
    """The thresholds that get the most development actions right; among equals, the highest, which is the gate that
    answers least and so cites the fewest wrong clauses. Candidates are the observed top scores plus infinity."""
    replay = _Replay(retriever)
    tops = sorted({replay.search(q.text, k=3)[0].score for q in questions if replay.search(q.text, k=3)} | {math.inf})
    best: tuple[tuple, ConfidenceGate] | None = None
    for upper in tops:
        for lower in (t for t in tops if t <= upper):
            gate = ConfidenceGate(tau_upper=upper, tau_lower=lower)
            explainer = PolicyExplainer(corpus, replay, gate)
            key = (sum(_is_correct(q, *_outcome(explainer, q)) for q in questions), upper, lower)
            if best is None or key > best[0]:
                best = (key, gate)
    return best[1]


def _metrics(rows: list[tuple[PolicyQuestion, list[str], str, str | None, float]]) -> dict[str, Any]:
    ranked = [(q, ranking) for q, ranking, _, _, _ in rows if q.expected_clause_ids]
    reciprocal = [next((1 / (i + 1) for i, cid in enumerate(ranking) if cid in q.expected_clause_ids), 0.0) for q, ranking in ranked]
    answered = [(q, c) for q, _, a, c, _ in rows if a == "answer"]
    expect_answer = [a for q, _, a, _, _ in rows if q.expected_action == "answer"]
    expect_abstain = [a for q, _, a, _, _ in rows if q.expected_action == "abstain"]
    latencies = [ms for *_, ms in rows]
    return {
        "n": len(rows),
        "recall_at_1": _ratio(sum(ranking[0] in q.expected_clause_ids for q, ranking in ranked if ranking), len(ranked)),
        "recall_at_3": _ratio(sum(bool(set(ranking[:3]) & set(q.expected_clause_ids)) for q, ranking in ranked), len(ranked)),
        "mrr": {"value": (sum(reciprocal) / len(reciprocal)) if reciprocal else None, "denominator": len(reciprocal)},
        "correct_action": _ratio(sum(_is_correct(q, a, c) for q, _, a, c, _ in rows), len(rows)),
        "oos_abstained": _ratio(sum(a == "abstain" for a in expect_abstain), len(expect_abstain)),
        "wrong_abstention": _ratio(sum(a == "abstain" for a in expect_answer), len(expect_answer)),
        "wrong_citation": _ratio(sum(c not in q.expected_clause_ids for q, c in answered), len(answered)),
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)},
    }


def measure(questions: list[PolicyQuestion], corpus: PolicyCorpus, retriever, gate: ConfidenceGate) -> dict[str, Any]:
    """Retrieval and gate metrics at fixed thresholds, overall and by language."""
    explainer = PolicyExplainer(corpus, retriever, gate)
    rows = []
    for q in questions:
        start = time.perf_counter()
        action, clause = _outcome(explainer, q)
        latency = (time.perf_counter() - start) * 1000
        ranking = [h.clause_id for h in retriever.search(q.text, k=len(corpus.clauses))]
        rows.append((q, ranking, action, clause, latency))
    return {"all": _metrics(rows), **{lang: _metrics([r for r in rows if r[0].language == lang]) for lang in LANGUAGES}}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _frozen(test_path: Path) -> str:
    recorded = Path(test_path).with_suffix(".sha256")
    if not recorded.exists():
        return "not frozen"
    if recorded.read_text(encoding="utf-8").split()[0] != _sha256(test_path):
        raise ValueError(f"{test_path} no longer matches {recorded.name}: the frozen test split changed")
    return "matches its SHA-256"


def benchmark(dev_path: str | Path, test_path: str | Path, corpus_path: Path = DEFAULT_CORPUS_PATH,
              retrievers: dict[str, Any] | None = None, e5_model_dir: str | Path | None = None) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    frozen = _frozen(Path(test_path))
    dev, test = load_questions(dev_path, corpus), load_questions(test_path, corpus)
    retrievers = retrievers or {"bm25": BM25Retriever(corpus)}
    if e5_model_dir is not None:
        retrievers = {**retrievers, "e5": E5Retriever(corpus, OnnxE5Embedder(Path(e5_model_dir)))}
    results = {}
    for name, retriever in retrievers.items():
        gate = calibrate(dev, corpus, retriever)
        results[name] = {"gate": {"tau_upper": gate.tau_upper, "tau_lower": gate.tau_lower},
                         "dev": measure(dev, corpus, retriever, gate), "test": measure(test, corpus, retriever, gate)}
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        commit = ""
    meta = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "commit": commit or "unknown",
            "corpus_sha256": _sha256(Path(corpus_path)),
            "dev": {"path": str(dev_path), "questions": len(dev), "sha256": _sha256(Path(dev_path)),
                    "provenance": ", ".join(sorted({q.provenance for q in dev}))},
            "test": {"path": str(test_path), "questions": len(test), "sha256": _sha256(Path(test_path)), "frozen": frozen,
                     "provenance": ", ".join(sorted({q.provenance for q in test}))}}
    if e5_model_dir is not None:  # its files matched their pinned SHA-256 when the embedder loaded
        meta["e5"] = {"model": MODEL_REPO, "revision": MODEL_REVISION, "model_dir": str(e5_model_dir)}
    return {"meta": meta, "retrievers": results}


def _mrr(value: dict[str, Any]) -> str:
    return "not defined (0 questions)" if value["value"] is None else f"{value['value']:.3f} (of {value['denominator']})"


def render_markdown(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    lines = ["# Policy explainer benchmark", "",
             f"Development split: `{meta['dev']['path']}`, {meta['dev']['questions']} questions ({meta['dev']['provenance']}). "
             f"Test split: `{meta['test']['path']}`, {meta['test']['questions']} questions ({meta['test']['provenance']}), "
             f"{meta['test']['frozen']}. Corpus SHA-256 `{meta['corpus_sha256'][:12]}`; commit {meta['commit']}. "
             "The thresholds come from the development split only; the test split is measured once with them. Offline "
             "results on team-written questions; the retrievers are deterministic, so one run."]
    if "e5" in meta:
        lines[-1] += f" E5: `{meta['e5']['model']}` at revision `{meta['e5']['revision'][:12]}`, int8 ONNX, files checked against their SHA-256."
    for name, result in payload["retrievers"].items():
        dev, test = result["dev"]["all"], result["test"]["all"]
        lines += ["", f"## {name} (gate: tau_upper {result['gate']['tau_upper']:.3f}, tau_lower {result['gate']['tau_lower']:.3f})", "",
                  "| Metric | Development | Test |", "| --- | --- | --- |"]
        for label, key in (("Recall@1", "recall_at_1"), ("Recall@3", "recall_at_3"), ("Correct action", "correct_action"),
                           ("Out-of-scope questions abstained", "oos_abstained"), ("Wrong abstention (an answer was expected)", "wrong_abstention"),
                           ("Wrong citation (of the answers given)", "wrong_citation")):
            lines.append(f"| {label} | {_fmt(dev[key])} | {_fmt(test[key])} |")
        lines.append(f"| MRR | {_mrr(dev['mrr'])} | {_mrr(test['mrr'])} |")
        latency = [f"{s['latency_ms']['p50']:.2f} / {s['latency_ms']['p95']:.2f}" if s["latency_ms"]["p50"] is not None else "n/a" for s in (dev, test)]
        lines.append(f"| Latency p50 / p95 (ms, in-process) | {latency[0]} | {latency[1]} |")
        lines += ["", "Slice by language (small samples; read the counts, not the rates):", "",
                  "| Language | Split | n | Recall@3 | Correct action | Wrong citation |", "| --- | --- | --- | --- | --- | --- |"]
        for lang in LANGUAGES:
            for split in ("dev", "test"):
                s = result[split][lang]
                lines.append(f"| {lang} | {split} | {s['n']} | {_fmt(s['recall_at_3'])} | {_fmt(s['correct_action'])} | {_fmt(s['wrong_citation'])} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Benchmark the policy explainer and calibrate its gate on the development split.")
    parser.add_argument("--dev", default=str(DEFAULT_DEV), help="development split (JSONL)")
    parser.add_argument("--test", default=str(DEFAULT_TEST), help="test split (JSONL), frozen by <test>.sha256 when present")
    parser.add_argument("--out", default="reports/rag_benchmark", help="output prefix (writes <out>.json and <out>.md)")
    parser.add_argument("--write-gate", metavar="PATH", help="write the BM25 gate file that turns the explainer on")
    parser.add_argument("--e5", metavar="MODEL_DIR", help="also measure E5 with the model in MODEL_DIR "
                        "(uv run python -m src.rag.onnx_retriever download); the gate file stays BM25's")
    args = parser.parse_args(argv)
    for path in (args.dev, args.test):
        if not Path(path).exists():
            parser.error(f"{path} does not exist: the team writes the question bank (roadmap Task 1.2)")
    payload = benchmark(args.dev, args.test, e5_model_dir=args.e5)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    for name, result in payload["retrievers"].items():
        print(f"{name}: gate {result['gate']}, test correct action {_fmt(result['test']['all']['correct_action'])}")
    print(f"wrote {out}.md and {out}.json")
    bm25 = payload["retrievers"]["bm25"]
    if args.write_gate:
        meta = payload["meta"]
        gate = {"retriever": "bm25", **bm25["gate"], "calibrated_on": meta["dev"]["path"], "dev_sha256": meta["dev"]["sha256"],
                "corpus_sha256": meta["corpus_sha256"], "commit": meta["commit"]}
        Path(args.write_gate).write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.write_gate}: the explainer turns on at the next start")


if __name__ == "__main__":
    main()
