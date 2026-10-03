"""Markdown report: baseline and proposed on the same cases, every metric with its denominator (brief section 5)."""
from __future__ import annotations

from typing import Any


def _fmt(ratio: dict[str, Any]) -> str:
    if ratio["denominator"] == 0 or ratio["rate"] is None:
        return f"not defined (0 of {ratio['denominator']})"
    return f"{ratio['rate'] * 100:.1f} % ({ratio['numerator']} of {ratio['denominator']})"


def render_markdown(metrics_by_system: dict[str, dict[str, Any]], meta: dict[str, Any]) -> str:
    systems = list(metrics_by_system)
    lines = [f"# Evaluation report: {meta.get('suite', 'suite')}", ""]
    lines.append(f"Cases: {meta.get('n_cases')} ({meta.get('mix', '')}). Provenance: {meta.get('provenance', '')}. "
                 f"Repeats: {meta.get('repeats', 1)}. Systems: {', '.join(systems)}. Versions: {meta.get('versions', '')}. "
                 "Offline results on scripted cases, not production gains.")
    lines.append("")
    lines.append("| Metric | " + " | ".join(systems) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in systems) + " |")
    rows = [
        ("Safe automated resolution (eligible cases resolved correctly without a human)", lambda m: _fmt(m["safe_automated_resolution"])),
        ("Safe automated resolution over in-scope cases (disputes, without out-of-scope requests or API attacks)",
         lambda m: _fmt(m["safe_automated_resolution_in_scope"])),
        ("Attempted automation share", lambda m: _fmt(m["attempted_automation_share"])),
        ("Containment (ended without transfer)", lambda m: _fmt(m["containment"])),
        ("Escalation precision", lambda m: _fmt(m["escalation_precision"])),
        ("Escalation recall", lambda m: _fmt(m["escalation_recall"])),
        ("Missed transfers", lambda m: str(m["missed_transfers"])),
        ("Unnecessary transfers", lambda m: str(m["unnecessary_transfers"])),
        ("Unsafe outcomes", lambda m: _fmt(m["unsafe_outcomes"])),
        ("Unsafe reasons", lambda m: ", ".join(f"{k}: {v}" for k, v in sorted(m["unsafe_reasons"].items())) or "none"),
        ("Exact outcome accuracy", lambda m: _fmt(m["outcome_accuracy"])),
        ("Reply language accuracy", lambda m: _fmt(m["reply_language_accuracy"])),
        ("Latency p50 / p95 (ms, in-process, no network)", lambda m: f"{m['latency_ms']['p50']:.1f} / {m['latency_ms']['p95']:.1f}"),
        ("Crashes", lambda m: str(m["crashes"])),
    ]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(metrics_by_system[s]) for s in systems) + " |")
    lines.append("")
    for dimension in ("language", "segment", "country"):
        lines.append(f"## Slice by {dimension} (small samples; read the counts, not the rates)")
        lines.append("")
        lines.append("| Value | System | n | Safe automated resolution | Unsafe outcomes | Outcome accuracy |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in systems:
            for value, m in metrics_by_system[s]["slices"][dimension].items():
                lines.append(f"| {value} | {s} | {m['n']} | {_fmt(m['safe_automated_resolution'])} | {_fmt(m['unsafe_outcomes'])} | {_fmt(m['outcome_accuracy'])} |")
        lines.append("")
    if meta.get("repeat_spread"):
        lines.append("## Run-to-run variability")
        lines.append("")
        for s, spread in meta["repeat_spread"].items():
            lines.append(f"- {s}: safe automated resolution rate min {spread['min']:.3f}, max {spread['max']:.3f} over {meta.get('repeats')} repeats; latency p50 min {spread['p50_min']:.1f} ms, max {spread['p50_max']:.1f} ms")
        lines.append("")
    lines.append("Cost per attempted case: 0 model tokens in rules-only mode (keyword extractor, policy as code); compute only. "
                 "Cost per successful automated resolution: not defined when there are no successes.")
    lines.append("")
    return "\n".join(lines)
