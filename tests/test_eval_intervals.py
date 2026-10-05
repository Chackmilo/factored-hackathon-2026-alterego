"""Uncertainty of the evaluation rates: Wilson intervals per rate and an exact paired test between two systems (audit finding H09)."""
import json

import pytest

from src.eval.intervals import compare_reports, mcnemar_exact, wilson_interval, write_intervals


def test_wilson_interval_matches_known_values():
    lo, hi = wilson_interval(105, 107)
    assert lo == pytest.approx(0.9344, abs=5e-4) and hi == pytest.approx(0.9949, abs=5e-4)
    lo, hi = wilson_interval(0, 25)  # zero failures in 25 cases is not zero risk
    assert lo == 0.0 and hi == pytest.approx(0.1332, abs=5e-4)
    assert wilson_interval(0, 0) == (None, None)


def test_mcnemar_exact_reads_only_the_discordant_pairs():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0
    assert mcnemar_exact(0, 10) == pytest.approx(2 * 0.5 ** 10)
    assert mcnemar_exact(1, 9) == pytest.approx(2 * (1 + 10) * 0.5 ** 10)


def _report(tmp_path, name, rows):
    """A report with one system: rows are (case_id, eligible, safe_resolution, unsafe)."""
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps({"case_id": c, "expected": {"final_outcome": "AUTONOMOUS_RESOLUTION" if e else "MANDATORY_HITL_ESCALATION"}})
                               for c, e, _, _ in rows), encoding="utf-8")
    results = [{"case_id": c, "safe_resolution": s, "unsafe_reasons": ["x"] if u else []} for c, _, s, u in rows]
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({"meta": {"versions": name}, "metrics": {}, "results": {"proposed": results}}), encoding="utf-8")
    return path, cases


def test_compare_reports_pairs_the_cases_and_counts_what_changed(tmp_path):
    a, cases = _report(tmp_path, "a", [("C1", True, True, False), ("C2", True, False, False), ("C3", False, False, True), ("C4", False, False, True)])
    b, _ = _report(tmp_path, "b", [("C1", True, True, False), ("C2", True, True, False), ("C3", False, False, False), ("C4", False, False, True)])
    out = compare_reports(a, "proposed", b, "proposed", cases)
    safe, unsafe = out["safe_automated_resolution"], out["unsafe_outcomes"]
    assert (safe["a"]["numerator"], safe["a"]["denominator"], safe["b"]["numerator"]) == (1, 2, 2)
    assert safe["only_a"] == 0 and safe["only_b"] == 1 and safe["p_value"] == 1.0
    assert (unsafe["a"]["numerator"], unsafe["b"]["numerator"], unsafe["a"]["denominator"]) == (2, 1, 4)
    assert unsafe["only_a"] == 1 and unsafe["only_b"] == 0
    assert safe["a"]["ci95"][0] < 0.5 < safe["a"]["ci95"][1]


def test_compare_reports_refuses_reports_of_different_cases(tmp_path):
    a, cases = _report(tmp_path, "a", [("C1", True, True, False)])
    b, _ = _report(tmp_path, "b", [("C9", True, True, False)])
    with pytest.raises(ValueError):
        compare_reports(a, "proposed", b, "proposed", cases)


def test_write_intervals_writes_markdown_and_json(tmp_path):
    a, cases = _report(tmp_path, "a", [("C1", True, True, False), ("C2", True, False, True)])
    b, _ = _report(tmp_path, "b", [("C1", True, True, False), ("C2", True, True, False)])
    payload = write_intervals([("a against b", a, "proposed", b, "proposed")], cases, tmp_path / "out")
    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "a against b" in text and "1 of 2" in text and "2 of 2" in text
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8")) == payload
