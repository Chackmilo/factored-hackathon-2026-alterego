"""
Uncertainty of the evaluation rates (audit of 29-Sep, finding H09): a Wilson 95 % interval for each rate and an exact
McNemar test for two systems that ran the same cases.

It reads the committed report JSONs and writes its own report, so the frozen reports and their figures stay as they are.

    uv run python -m src.eval.intervals --out reports/eval_intervals

The intervals describe sampling error only. The held-out cases come from a few templates (4 ways to dispute per language),
so they are less independent than the formulas assume: read the intervals as a lower bound on the uncertainty.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

Z95 = 1.959963984540054
ELIGIBLE_OUTCOME = "AUTONOMOUS_RESOLUTION"
DEFAULT_CASES = "data/eval/heldout_cases.jsonl"
DEFAULT_COMPARISONS = [
    ("Blind run (30-Sep): starter pipeline against the proposed stack, rules only", "reports/eval_heldout_blind.json", "baseline_starter",
     "reports/eval_heldout_blind.json", "proposed"),
    ("After the error analysis: starter pipeline against the proposed stack, rules only", "reports/eval_heldout.json", "baseline_starter",
     "reports/eval_heldout.json", "proposed"),
    ("Proposed stack: rules only against rules plus the transferred risk model", "reports/eval_heldout.json", "proposed",
     "reports/eval_heldout_model.json", "proposed"),
]


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = successes / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (0.0 if successes == 0 else max(0.0, center - half)), (1.0 if successes == n else min(1.0, center + half))


def mcnemar_exact(only_a: int, only_b: int) -> float:
    """Two-sided exact p-value on the pairs where the two systems disagree; 1.0 when none do."""
    n, k = only_a + only_b, min(only_a, only_b)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n)


def _rate(successes: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_interval(successes, n)
    return {"numerator": successes, "denominator": n, "rate": (successes / n) if n else None, "ci95": [lo, hi]}


def _load_cases(path: str | Path) -> dict[str, dict[str, Any]]:
    rows = (json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip().startswith("{"))
    return {c["case_id"]: c for c in rows}


def _results(path: str | Path, system: str) -> tuple[dict[str, dict[str, Any]], str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return {r["case_id"]: r for r in payload["results"][system]}, str(payload.get("meta", {}).get("versions", ""))


def _paired(ids: list[str], a: dict[str, bool], b: dict[str, bool]) -> dict[str, Any]:
    only_a, only_b = sum(a[i] and not b[i] for i in ids), sum(b[i] and not a[i] for i in ids)
    return {"a": _rate(sum(a[i] for i in ids), len(ids)), "b": _rate(sum(b[i] for i in ids), len(ids)),
            "only_a": only_a, "only_b": only_b, "p_value": mcnemar_exact(only_a, only_b)}


def compare_reports(report_a: str | Path, system_a: str, report_b: str | Path, system_b: str, cases_path: str | Path = DEFAULT_CASES) -> dict[str, Any]:
    cases = _load_cases(cases_path)
    (ra, va), (rb, vb) = _results(report_a, system_a), _results(report_b, system_b)
    if set(ra) != set(rb) or not set(ra) <= set(cases):
        raise ValueError("the two reports do not hold the same cases of this suite")
    ids = sorted(ra)
    eligible = [i for i in ids if cases[i]["expected"].get("final_outcome") == ELIGIBLE_OUTCOME]
    return {"a": {"report": str(report_a), "system": system_a, "versions": va}, "b": {"report": str(report_b), "system": system_b, "versions": vb},
            "n_cases": len(ids),
            "safe_automated_resolution": _paired(eligible, {i: bool(ra[i]["safe_resolution"]) for i in ids}, {i: bool(rb[i]["safe_resolution"]) for i in ids}),
            "unsafe_outcomes": _paired(ids, {i: bool(ra[i]["unsafe_reasons"]) for i in ids}, {i: bool(rb[i]["unsafe_reasons"]) for i in ids})}


def _fmt(r: dict[str, Any]) -> str:
    if not r["denominator"]:
        return "not defined (0 of 0)"
    return f"{r['rate'] * 100:.1f} % ({r['numerator']} of {r['denominator']}), 95 % interval {r['ci95'][0] * 100:.1f} to {r['ci95'][1] * 100:.1f} %"


def _p(p: float) -> str:
    return "under 0.001" if p < 0.001 else f"{p:.3f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = ["# Evaluation intervals and paired tests", "",
             f"Suite: `{payload['cases']}`. Wilson 95 % intervals for each rate; exact McNemar test on the cases where the two systems disagree. "
             "Written by `src/eval/intervals.py` from the committed report JSONs. Offline results on scripted cases, not production gains.", "",
             "The intervals cover sampling error only. The cases come from a few templates, so they are less independent than the formulas assume: "
             "read each interval as a lower bound on the uncertainty.", ""]
    for c in payload["comparisons"]:
        lines += [f"## {c['title']}", "", f"- A: `{c['a']['system']}` in `{c['a']['report']}` ({c['a']['versions']})",
                  f"- B: `{c['b']['system']}` in `{c['b']['report']}` ({c['b']['versions']})", "",
                  "| Metric | A | B | Only A | Only B | Exact p |", "| --- | --- | --- | --- | --- | --- |"]
        for key, label in (("safe_automated_resolution", "Safe automated resolution (eligible cases)"), ("unsafe_outcomes", "Unsafe outcomes (all cases)")):
            m = c[key]
            lines.append(f"| {label} | {_fmt(m['a'])} | {_fmt(m['b'])} | {m['only_a']} | {m['only_b']} | {_p(m['p_value'])} |")
        lines.append("")
    lines += ["\"Only A\" counts the cases where A has the outcome and B does not (a safe resolution in the first row, an unsafe outcome in the second); "
              "\"Only B\" is the reverse.", ""]
    return "\n".join(lines)


def write_intervals(comparisons: list[tuple[str, str, str, str, str]], cases_path: str | Path, out_prefix: str | Path) -> dict[str, Any]:
    payload = {"cases": str(cases_path), "method": "Wilson 95 % interval; exact two-sided McNemar test",
               "comparisons": [{"title": title, **compare_reports(a, sa, b, sb, cases_path)} for title, a, sa, b, sb in comparisons]}
    out = Path(out_prefix)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Wilson intervals and exact paired tests over the committed evaluation reports")
    parser.add_argument("--cases", default=DEFAULT_CASES)
    parser.add_argument("--out", default="reports/eval_intervals")
    args = parser.parse_args()
    comparisons = [c for c in DEFAULT_COMPARISONS if Path(c[1]).exists() and Path(c[3]).exists()]
    payload = write_intervals(comparisons, args.cases, args.out)
    print(f"{len(payload['comparisons'])} comparisons written to {args.out}.md and {args.out}.json")


if __name__ == "__main__":
    main()
