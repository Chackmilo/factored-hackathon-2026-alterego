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


def load_risk_scorer(path: str | Path):
    """The transferred risk model the API serves (src/ml/transfer_scorer.py), loaded only when a run asks for it."""
    from src.ml.transfer_scorer import TransferRiskScorer

    return TransferRiskScorer(path)


def load_explainer(gate_path: str | Path):
    """The policy explainer the API serves, built from its gate file (data/rag_gate.json), loaded only when a run asks for it."""
    from src.rag.policy_explainer import load_policy_explainer

    explainer = load_policy_explainer(Path(gate_path))
    if explainer is None:
        raise FileNotFoundError(f"no gate file at {gate_path}: the explainer is off without one")
    return explainer


def run_suite(cases_path: str | Path, out_prefix: str | Path, repeats: int = 1, systems: tuple[str, ...] = ("baseline_starter", "proposed"),
              model_path: str | Path | None = None, explainer_gate: str | Path | None = None) -> dict:
    cases = load_cases(cases_path)
    scorer = load_risk_scorer(model_path) if model_path else None
    explainer = load_explainer(explainer_gate) if explainer_gate else None
    per_system_runs: dict[str, list] = {s: [] for s in systems}
    with tempfile.TemporaryDirectory() as workdir:
        for _ in range(repeats):
            for system in systems:
                if system == "proposed":
                    results = [run_case_proposed(c, workdir, risk_scorer=scorer, explainer=explainer) for c in cases]
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
            "versions": f"commit {commit}; extractor keyword-v1; policy v2.3; "
                        + (f"risk model {Path(model_path).name} (threshold {scorer.policy_threshold:.4g})" if scorer else "no ML model")
                        + ", no LLM" + (f"; policy explainer bm25 ({Path(explainer_gate).name})" if explainer else "")}
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
    parser.add_argument("--model", default=None, help="risk model bundle for the proposed stack (models/fraud_risk_ieee.joblib); rules-only without")
    parser.add_argument("--explainer", default=None, metavar="GATE", help="gate file of the policy explainer (data/rag_gate.json), as production serves it; off without")
    args = parser.parse_args()
    payload = run_suite(args.cases, args.out, repeats=args.repeats, systems=tuple(args.systems.split(",")), model_path=args.model,
                        explainer_gate=args.explainer)
    for system, metrics in payload["metrics"].items():
        sar = metrics["safe_automated_resolution"]
        print(f"{system}: safe automated resolution {sar['numerator']}/{sar['denominator']}, unsafe {metrics['unsafe_outcomes']['numerator']}/{metrics['n_cases']}, "
              f"missed {metrics['missed_transfers']}, unnecessary {metrics['unnecessary_transfers']}, p50 {metrics['latency_ms']['p50']:.1f} ms")
    print(f"wrote {args.out}.md and {args.out}.json")


if __name__ == "__main__":
    main()
