"""
Benchmark of the policy explainer (roadmap Task 4.1): the question bank format, retrieval and gate metrics, the gate
calibrated on the development split only, the frozen test split and the gate file that turns the explainer on. The
banks here are team-written test fixtures; the team's evaluation bank (Task 1.2) never tunes them.
"""
import hashlib
import json

import pytest

from src.eval.rag_benchmark import (
    PolicyQuestion,
    benchmark,
    calibrate,
    load_questions,
    main,
    measure,
)
from src.rag.bm25_retriever import Hit
from src.rag.corpus import load_corpus
from src.rag.gate import ConfidenceGate
from src.rag.policy_explainer import load_policy_explainer

CORPUS = load_corpus()


class FakeRetriever:
    """Scores fixed per question, to put chosen clauses and scores in front of the gate."""

    name = "fake"

    def __init__(self, rankings: dict[str, list[tuple[str, float]]]):
        self.rankings = rankings

    def search(self, text: str, k: int = 3) -> list[Hit]:
        return [Hit(clause_id, score) for clause_id, score in self.rankings[text][:k]]


def row(question_id, text, action, clause_ids, language="es"):
    return {"question_id": question_id, "language": language, "text": text, "expected_action": action,
            "expected_clause_ids": clause_ids, "provenance": "team-generated"}


def question(question_id, action, clause_ids):
    return PolicyQuestion(question_id, "es", question_id, action, tuple(clause_ids), "team-generated")


def bank(tmp_path, name, rows):
    path = tmp_path / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


# Dev scores built so that only tau_upper = 6.0 and tau_lower = 3.0 get all four dev actions right.
RANKINGS = {
    "a1": [("POL-WIN-60", 8.0), ("POL-DISP-TYPE", 1.0)],
    "a2": [("POL-DISP-TYPE", 6.0), ("POL-WIN-60", 1.0)],
    "c1": [("POL-WIN-60", 3.0), ("POL-DISP-TYPE", 2.9)],
    "x1": [("POL-WIN-60", 0.5)],
    "t1": [("POL-WIN-60", 5.0), ("POL-DISP-TYPE", 1.0)],  # test: answered with thresholds chosen on test, not on dev
}
DEV = [row("a1", "a1", "answer", ["POL-WIN-60"]), row("a2", "a2", "answer", ["POL-DISP-TYPE"]),
       row("c1", "c1", "clarify", ["POL-WIN-60", "POL-DISP-TYPE"]), row("x1", "x1", "abstain", [])]
TEST = [row("t1", "t1", "answer", ["POL-WIN-60"])]


@pytest.mark.parametrize("field, value", [
    ("expected_action", "maybe"), ("language", "en"), ("expected_clause_ids", ["POL-NOPE"]),
    ("expected_clause_ids", []),  # an answer names no clause
    ("expected_action", "abstain"),  # an abstention names a clause
    ("provenance", None),  # missing
])
def test_a_question_row_that_breaks_the_format_is_refused(tmp_path, field, value):
    bad = row("q1", "¿Cuánto tiempo tengo?", "answer", ["POL-WIN-60"])
    if value is None:
        del bad[field]
    else:
        bad[field] = value
    with pytest.raises(ValueError):
        load_questions(bank(tmp_path, "bank.jsonl", [bad]), CORPUS)


def test_a_repeated_question_id_is_refused(tmp_path):
    rows = [row("q1", "uno", "abstain", []), row("q1", "dos", "abstain", [])]
    with pytest.raises(ValueError):
        load_questions(bank(tmp_path, "bank.jsonl", rows), CORPUS)


def test_retrieval_metrics_count_only_the_questions_that_expect_a_clause():
    rankings = {
        "q1": [("POL-WIN-60", 9.0), ("POL-DISP-TYPE", 1.0), ("POL-AUT-LOCK", 0.5), ("POL-CLARIFY", 0.2)],
        "q2": [("POL-WIN-60", 9.0), ("POL-DISP-TYPE", 8.0), ("POL-AUT-LOCK", 0.5), ("POL-CLARIFY", 0.2)],
        "q3": [("POL-WIN-60", 9.0), ("POL-DISP-TYPE", 8.0), ("POL-CLARIFY", 7.0), ("POL-AUT-LOCK", 6.0)],
        "q4": [("POL-WIN-60", 0.1)],
    }
    questions = [question("q1", "answer", ["POL-WIN-60"]), question("q2", "answer", ["POL-DISP-TYPE"]),
                 question("q3", "answer", ["POL-AUT-LOCK"]), question("q4", "abstain", [])]
    metrics = measure(questions, CORPUS, FakeRetriever(rankings), ConfidenceGate(tau_upper=5.0, tau_lower=1.0))["all"]
    assert (metrics["recall_at_1"]["numerator"], metrics["recall_at_1"]["denominator"]) == (1, 3)
    assert (metrics["recall_at_3"]["numerator"], metrics["recall_at_3"]["denominator"]) == (2, 3)
    assert metrics["mrr"]["value"] == pytest.approx((1 + 1 / 2 + 1 / 4) / 3)


def test_the_gate_metrics_count_wrong_citations_wrong_abstentions_and_redirects():
    rankings = {
        "w1": [("POL-DISP-TYPE", 9.0), ("POL-WIN-60", 1.0)],  # answered with the wrong clause
        "w2": [("POL-AUT-LOCK", 0.1)],  # an answer that abstains
        "w3": [("POL-WIN-60", 0.1)],  # an abstention that abstains
        "r1": [("POL-AUT-150", 9.0)],  # an internal clause redirects: it counts as an answer
    }
    questions = [question("w1", "answer", ["POL-WIN-60"]), question("w2", "answer", ["POL-AUT-LOCK"]),
                 question("w3", "abstain", []), question("r1", "answer", ["POL-AUT-150"])]
    metrics = measure(questions, CORPUS, FakeRetriever(rankings), ConfidenceGate(tau_upper=5.0, tau_lower=1.0))["all"]
    counts = {name: (metrics[name]["numerator"], metrics[name]["denominator"])
              for name in ("correct_action", "wrong_citation", "wrong_abstention", "oos_abstained")}
    assert counts == {"correct_action": (2, 4), "wrong_citation": (1, 2), "wrong_abstention": (1, 3), "oos_abstained": (1, 1)}


def test_calibration_keeps_the_thresholds_that_get_every_dev_action_right(tmp_path):
    dev = load_questions(bank(tmp_path, "dev.jsonl", DEV), CORPUS)
    gate = calibrate(dev, CORPUS, FakeRetriever(RANKINGS))
    assert (gate.tau_upper, gate.tau_lower) == (6.0, 3.0)


def test_when_dev_cannot_be_separated_calibration_picks_the_gate_that_answers_least(tmp_path):
    # Same score, different expectations: answering both cites a wrong clause; abstaining on both gets one right too.
    rankings = {"same-a": [("POL-WIN-60", 5.0)], "same-b": [("POL-DISP-TYPE", 5.0)]}
    dev = load_questions(bank(tmp_path, "dev.jsonl", [row("same-a", "same-a", "answer", ["POL-WIN-60"]),
                                                      row("same-b", "same-b", "abstain", [])]), CORPUS)
    gate = calibrate(dev, CORPUS, FakeRetriever(rankings))
    assert (gate.tau_upper, gate.tau_lower) == (float("inf"), float("inf"))


def test_the_test_split_is_measured_with_the_thresholds_the_dev_split_chose(tmp_path):
    payload = benchmark(bank(tmp_path, "dev.jsonl", DEV), bank(tmp_path, "test.jsonl", TEST),
                        retrievers={"fake": FakeRetriever(RANKINGS)})
    fake = payload["retrievers"]["fake"]
    assert fake["gate"] == {"tau_upper": 6.0, "tau_lower": 3.0}
    assert (fake["dev"]["all"]["correct_action"]["numerator"], fake["dev"]["all"]["correct_action"]["denominator"]) == (4, 4)
    assert (fake["test"]["all"]["correct_action"]["numerator"], fake["test"]["all"]["correct_action"]["denominator"]) == (0, 1)


def test_a_frozen_test_split_must_still_match_its_hash(tmp_path):
    dev, test = bank(tmp_path, "dev.jsonl", DEV), bank(tmp_path, "test.jsonl", TEST)
    retrievers = {"fake": FakeRetriever(RANKINGS)}
    assert benchmark(dev, test, retrievers=retrievers)["meta"]["test"]["frozen"] == "not frozen"
    digest = hashlib.sha256(test.read_bytes()).hexdigest()
    test.with_suffix(".sha256").write_text(f"{digest}  {test.name}\n", encoding="utf-8")
    assert benchmark(dev, test, retrievers=retrievers)["meta"]["test"]["frozen"] == "matches its SHA-256"
    test.write_text(test.read_text(encoding="utf-8") + json.dumps(row("t2", "t1", "abstain", [])) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        benchmark(dev, test, retrievers=retrievers)


def test_the_cli_writes_the_report_and_writes_the_gate_only_when_asked(tmp_path):
    dev = bank(tmp_path, "dev.jsonl", [
        row("D-01", "¿Cuánto tiempo tengo para disputar un cargo?", "answer", ["POL-WIN-60"]),
        row("D-02", "Quanto tempo tenho para contestar uma cobrança?", "answer", ["POL-WIN-60"], language="pt"),
        row("D-03", "¿Puedo disputar un depósito o un movimiento pendiente?", "answer", ["POL-DISP-TYPE"]),
        row("D-04", "xyzzy plugh", "abstain", []),
    ])
    test = bank(tmp_path, "test.jsonl", [
        row("T-01", "Como faço para desbloquear o cartão?", "answer", ["POL-AUT-LOCK"], language="pt"),
        row("T-02", "qwerty asdf", "abstain", []),
    ])
    out, gate_path = tmp_path / "rag_benchmark", tmp_path / "rag_gate.json"
    main(["--dev", str(dev), "--test", str(test), "--out", str(out)])
    report = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert out.with_suffix(".md").read_text(encoding="utf-8").startswith("# ")
    assert report["retrievers"]["bm25"]["test"]["pt"]["n"] == 1 and not gate_path.exists()
    main(["--dev", str(dev), "--test", str(test), "--out", str(out), "--write-gate", str(gate_path)])
    explainer = load_policy_explainer(gate_path)
    assert {"tau_upper": explainer.gate.tau_upper, "tau_lower": explainer.gate.tau_lower} == report["retrievers"]["bm25"]["gate"]


def test_the_cli_names_the_missing_question_bank(tmp_path):
    with pytest.raises(SystemExit):
        main(["--dev", str(tmp_path / "missing.jsonl"), "--test", str(tmp_path / "missing.jsonl"), "--out", str(tmp_path / "r")])
