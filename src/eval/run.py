"""
CLI: run a case suite through the proposed stack and the reference baseline, write JSON and Markdown reports.

    uv run python -m src.eval.run data/eval/dev_cases.jsonl --out reports/eval_dev --repeats 3
"""
from __future__ import annotations

import os

# The harness mints local tokens for its attack cases and never runs in production: without this, a .env that has a
# SUPABASE_URL and no APP_ENV imports the app as production and those cases crash instead of being judged.
os.environ.setdefault("APP_ENV", "test")

import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from src.eval.baseline_adapter import run_case_baseline
from src.eval.cases import load_cases
from src.eval.metrics import compute_metrics
from src.eval.report import render_markdown
from src.eval.runner import run_case_proposed


def run_suite(cases_path: str | Path, out_prefix: str | Path, repeats: int = 1, systems: tuple[str, ...] = ("baseline_starter", "proposed")) -> dict:
    cases = load_cases(cases_path)
    per_system_runs: dict[str, list] = {s: [] for s in systems}
    with tempfile.TemporaryDirectory() as workdir:
        for _ in range(repeats):
            for system in systems:
                if system == "proposed":
                    results = [run_case_proposed(c, workdir) for c in cases]
                else:
                    results = [run_case_baseline(c) for c in cases]
                per_system_runs[system].append(results)
    metrics_by_system = {s: compute_metrics(cases, runs[-1]) for s, runs in per_system_runs.items()}
    spread = {}
    for s, runs in per_system_runs.items():
        rates = [compute_metrics(cases, r)["safe_automated_resolution"]["rate"] or 0.0 for r in runs]
        p50s = [compute_metrics(cases, r)["latency_ms"]["p50"] or 0.0 for r in runs]
        spread[s] = {"min": min(rates), "max": max(rates), "p50_min": min(p50s), "p50_max": max(p50s)}
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        commit = "unknown"
    mix = ", ".join(f"{k}: {v}" for k, v in sorted(Counter(c.category for c in cases).items()))
    meta = {"suite": Path(cases_path).name, "n_cases": len(cases), "mix": mix, "repeats": repeats, "repeat_spread": spread,
            "provenance": ", ".join(sorted({c.provenance for c in cases})),
            "versions": f"commit {commit}; extractor keyword-v1; policy v2.3; no ML model, no LLM"}
    out_prefix = Path(out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "metrics": metrics_by_system,
               "results": {s: [r.as_dict() for r in runs[-1]] for s, runs in per_system_runs.items()}}
    out_prefix.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str))
    out_prefix.with_suffix(".md").write_text(render_markdown(metrics_by_system, meta))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the dispute-intake evaluation harness.")
    parser.add_argument("cases", help="JSONL case file")
    parser.add_argument("--out", default="reports/eval", help="output prefix (writes <out>.json and <out>.md)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--systems", default="baseline_starter,proposed")
    args = parser.parse_args()
    payload = run_suite(args.cases, args.out, repeats=args.repeats, systems=tuple(args.systems.split(",")))
    for system, metrics in payload["metrics"].items():
        sar = metrics["safe_automated_resolution"]
        print(f"{system}: safe automated resolution {sar['numerator']}/{sar['denominator']}, unsafe {metrics['unsafe_outcomes']['numerator']}/{metrics['n_cases']}, "
              f"missed {metrics['missed_transfers']}, unnecessary {metrics['unnecessary_transfers']}, p50 {metrics['latency_ms']['p50']:.1f} ms")
    print(f"wrote {args.out}.md and {args.out}.json")


if __name__ == "__main__":
    main()
