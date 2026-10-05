"""Hypothesis 4: the keyword extractor, Jev and a mix of both read a bank of customer messages; exact topic sets, paired test, calibration."""
import json
from pathlib import Path

import pytest

from src.eval.intent_benchmark import (
    Reading,
    calibration,
    keyword_reading,
    labels_of,
    load_messages,
    mix,
    run,
    score,
)
from src.understand.jev_extractor import JevSignals, StubJev

DEV, TEST = Path("data/eval/intent_messages_dev.jsonl"), Path("data/eval/intent_messages_test.jsonl")


def test_the_bank_is_balanced_labeled_and_its_test_split_is_frozen():
    dev, test = load_messages(DEV), load_messages(TEST)
    assert (len(dev), len(test)) == (40, 100)
    for split in (dev, test):
        assert sum(m.language == "es" for m in split) == sum(m.language == "pt" for m in split)
        assert len({m.message_id for m in split}) == len(split) and all(m.provenance == "team-generated, LLM-drafted" for m in split)
    assert not {m.text for m in dev} & {m.text for m in test}
    import hashlib
    assert Path("data/eval/intent_messages_test.sha256").read_text(encoding="utf-8").split()[0] == hashlib.sha256(TEST.read_bytes()).hexdigest()


def test_a_bank_with_an_unknown_label_is_refused(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"message_id": "X-1", "language": "es", "text": "hola", "expected_topics": ["saludo"], "provenance": "team-generated"}) + "\n",
                   encoding="utf-8")
    with pytest.raises(ValueError):
        load_messages(bad)


def test_topics_reduce_to_the_four_labels_and_the_category_of_the_other_request():
    assert labels_of(["tarjeta_perdida_o_robada", "cobro_indebido", "saldo_o_extracto"]) == (frozenset({"tarjeta", "disputa", "fuera"}), "saldo_o_extracto")
    assert labels_of(["pregunta_sobre_reglas"]) == (frozenset({"reglas"}), None) and labels_of([]) == (frozenset(), None)


def test_the_keyword_reading_says_when_it_is_not_sure_of_itself():
    sure = keyword_reading("No reconozco un cargo de 80 dólares en Oxxo.")
    assert sure.labels == {"disputa"} and sure.sure
    guessed = keyword_reading("Hay un cargo de 80 dólares de una tienda de apps.")  # a charge word and an amount, no dispute phrase
    assert guessed.labels == {"disputa"} and not guessed.sure
    nothing = keyword_reading("Alguien usó mi cuenta para sacar plata, yo no fui.")
    assert nothing.labels == set() and not nothing.sure
    assert keyword_reading("Perdí mi tarjeta de crédito esta mañana.").sure


def test_the_mix_calls_jev_only_when_the_keywords_are_not_sure():
    sure = Reading(frozenset({"disputa"}), None, sure=True)
    unsure = Reading(frozenset({"disputa"}), None, sure=False)
    jev = Reading(frozenset({"tarjeta"}), None)
    assert mix(sure, jev, "gate") == (sure.labels, None, False)  # no call, the keyword reading stands
    assert mix(unsure, jev, "gate") == (frozenset({"tarjeta"}), None, True)
    assert mix(unsure, jev, "gate_union") == (frozenset({"tarjeta", "disputa"}), None, True)
    with pytest.raises(ValueError):
        mix(sure, jev, "other")


def test_score_counts_exact_sets_and_each_label():
    expected = [frozenset({"disputa"}), frozenset({"disputa", "tarjeta"}), frozenset()]
    got = [frozenset({"disputa"}), frozenset({"disputa"}), frozenset({"fuera"})]
    s = score(expected, got)
    assert (s["exact"]["numerator"], s["exact"]["denominator"]) == (1, 3)
    assert s["labels"]["disputa"] == {"tp": 2, "fp": 0, "fn": 0} and s["labels"]["tarjeta"] == {"tp": 0, "fp": 0, "fn": 1}
    assert s["labels"]["fuera"] == {"tp": 0, "fp": 1, "fn": 0}


def test_calibration_gives_the_brier_score_and_the_expected_calibration_error():
    perfect = calibration([1.0, 0.0, 1.0, 0.0], [True, False, True, False])
    assert perfect["brier"] == 0.0 and perfect["ece"] == 0.0
    off = calibration([0.9, 0.9, 0.9, 0.9], [True, True, False, False])
    assert off["brier"] == pytest.approx(0.41) and off["ece"] == pytest.approx(0.4) and off["n"] == 4


def test_a_run_with_a_stub_engine_writes_the_three_readings_the_paired_test_and_the_calibration(tmp_path):
    payload = run(DEV, DEV, tmp_path / "h4", jev=StubJev(answers={}), frozen_check=False)
    for split in ("dev", "test"):
        block = payload[split]
        assert set(block["engines"]) == {"keyword", "jev", "gate", "gate_union"}
        assert block["engines"]["keyword"]["all"]["exact"]["denominator"] == 40
        assert {"es", "pt", "all"} <= set(block["engines"]["jev"]) and "p_value" in block["keyword_vs_jev"]
        assert set(block["calibration"]["es"]) == {"dispute", "stolen_card", "other_request"}
        assert 0.0 <= block["engines"]["gate"]["jev_call_share"] <= 1.0
    assert payload["chosen_mix"] in ("gate", "gate_union")
    assert (tmp_path / "h4.md").exists() and json.loads((tmp_path / "h4.json").read_text(encoding="utf-8"))["chosen_mix"] == payload["chosen_mix"]


def test_a_run_without_jev_measures_the_keyword_extractor_alone(tmp_path):
    payload = run(DEV, DEV, tmp_path / "kw", frozen_check=False)
    assert set(payload["dev"]["engines"]) == {"keyword"} and payload["chosen_mix"] is None


def test_a_changed_test_split_is_refused(tmp_path):
    changed = tmp_path / "intent_messages_test.jsonl"
    changed.write_text(DEV.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "intent_messages_test.sha256").write_text("0" * 64 + "  intent_messages_test.jsonl\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run(DEV, changed, tmp_path / "x")
    assert JevSignals  # the stub's answers use the same type the real adapter returns
