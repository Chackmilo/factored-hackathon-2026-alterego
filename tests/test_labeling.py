"""Labeling kit for the held-out suite (TQ-018): four labelers, 50 double-labeled cases, Cohen's kappa."""
import csv
from collections import Counter
from pathlib import Path

import pytest

from src.eval.labeling import LABEL_FIELDS, cohen_kappa, export, kappa_report

SUITE = Path("data/eval/heldout_cases.jsonl")


def test_cohen_kappa_matches_hand_computed_values():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    # observed agreement 0.5, chance agreement 0.5 -> 0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    # 2x2 table [[20, 5], [10, 15]]: po = 0.70, pe = 0.5 * 0.6 + 0.5 * 0.4 = 0.50 -> 0.40
    first = ["y"] * 25 + ["n"] * 25
    second = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohen_kappa(first, second) == pytest.approx(0.40)


def test_export_spreads_the_suite_with_fifty_double_labeled_cases(tmp_path):
    export(SUITE, tmp_path)
    sheets = {p.stem: list(csv.DictReader(p.open(encoding="utf-8"))) for p in sorted(tmp_path.glob("labels_*.csv"))}
    assert set(sheets) == {"labels_A", "labels_B", "labels_C", "labels_D"}
    appearances = Counter(row["case_id"] for rows in sheets.values() for row in rows)
    assert len(appearances) == 250 and Counter(appearances.values()) == {1: 200, 2: 50}
    assert {len(rows) for rows in sheets.values()} == {75}
    row = next(iter(sheets.values()))[0]
    assert all(row[field] == "" for field in LABEL_FIELDS)
    assert "expected" not in row and "design" not in " ".join(row).lower()


def test_kappa_report_reads_the_filled_sheets(tmp_path):
    export(SUITE, tmp_path)
    for path in tmp_path.glob("labels_*.csv"):
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        for row in rows:
            row["final_outcome"], row["requires_human"] = "AUTONOMOUS_RESOLUTION", "no"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = kappa_report(tmp_path, SUITE)
    assert report["double_labeled"] == 50
    assert report["fields"]["final_outcome"]["agreement"] == 1.0
