"""
EDA of the 19 features the transferred risk model serves (DEPLOYABLE_V1), and its observed against predicted fraud.

For each feature: count, nulls, minimum, maximum, mean, median and standard deviation in both sources (the IEEE-CIS
competition and the bank's Web and App serving window), plus one chart with the two distributions and the observed
fraud rate of the competition along the feature. For the model: the predicted probability against the observed fraud
rate by score decile on the competition's train and holdout splits, and the daily observed and expected fraud counts
of the holdout. The bank label has no learnable signal, so the bank side only reports its flags by score decile.

    uv run python -m src.ml.risk_feature_eda --competition data/kaggle --lakehouse data/lakehouse_full.duckdb \
        --model models/fraud_risk_ieee.joblib --out reports/ml

Writes reports/ml/risk_feature_eda.md and .json and the charts in reports/ml/eda/. matplotlib is a dev dependency:
the API never imports this module (tests/test_runtime_dependencies.py).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402  (the backend has to be set before pyplot)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.bank_adapter import load_bank_canonical  # noqa: E402
from src.ml.feature_contract import (  # noqa: E402
    DEPLOYABLE_V1,
    FEATURE_PHRASES,
    build_contract_features,
)
from src.ml.ieee_cis_adapter import holdout_mask, load_competition  # noqa: E402

# Heavy right tails: binned and drawn on a log1p axis, labeled in the original unit.
LOG_AXIS = {"amount_usd", "days_since_prev_tx_card", "tx_count_card_1d", "tx_count_card_7d", "tx_count_card_30d", "tx_sum_card_7d",
            "amount_mean_card_hist", "amount_std_card_hist", "ratio_to_historical_avg"}
MAX_CATEGORIES = 8  # a feature with at most this many values gets one bar per value
SURFACE, INK, INK_SECONDARY, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e8e7e3"
COMPETITION_COLOR, BANK_COLOR = "#2a78d6", "#eb6834"  # checked for colorblind separation and contrast on the surface
SOURCE_LABELS = {"competition": "IEEE-CIS competition", "bank": "Bank, Web and App window"}


def _num(v: Any) -> float | None:
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def feature_stats(feats: pd.DataFrame, features: list[str], label: str | None = None) -> list[dict[str, Any]]:
    """Count, nulls, min, max, mean, median and standard deviation of each feature; with a label, the mean of each class."""
    rows = []
    for f in features:
        x = pd.to_numeric(feats[f], errors="coerce")
        v = x.dropna()
        row = {"feature": f, "phrase": FEATURE_PHRASES.get(f, f), "n": int(len(x)), "nulls": int(x.isna().sum()),
               "null_share": float(x.isna().mean()) if len(x) else None, "distinct": int(v.nunique()),
               "min": _num(v.min()) if len(v) else None, "max": _num(v.max()) if len(v) else None,
               "mean": _num(v.mean()) if len(v) else None, "median": _num(v.median()) if len(v) else None,
               "std": _num(v.std()) if len(v) > 1 else None}
        if label is not None:
            y = feats[label].to_numpy(int)
            row["mean_label_1"] = _num(x[y == 1].mean()) if (y == 1).any() else None
            row["mean_label_0"] = _num(x[y == 0].mean()) if (y == 0).any() else None
        rows.append(row)
    return rows


def calibration_table(y: np.ndarray, scores: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    """Equal-count score bins, lowest first: rows, mean predicted probability, observed positives and observed rate."""
    order = np.argsort(scores, kind="mergesort")
    out = []
    for i, idx in enumerate(np.array_split(order, bins), start=1):
        out.append({"bin": i, "n": int(len(idx)), "score_min": float(scores[idx].min()), "score_max": float(scores[idx].max()),
                    "mean_predicted": float(scores[idx].mean()), "positives": int(y[idx].sum()), "observed_rate": float(y[idx].mean())})
    return out


def daily_observed_expected(ts: pd.Series, y: np.ndarray, scores: np.ndarray) -> list[dict[str, Any]]:
    """Per day: rows, observed positives and the expected count (the sum of the predicted probabilities)."""
    df = pd.DataFrame({"day": pd.to_datetime(ts).dt.date.to_numpy(), "y": y, "s": scores})
    g = df.groupby("day", sort=True).agg(n=("y", "size"), observed=("y", "sum"), expected=("s", "sum"))
    return [{"day": str(day), "n": int(r.n), "observed": int(r.observed), "expected": float(r.expected)} for day, r in g.iterrows()]


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def _fmt(v: float) -> str:
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 10 or float(v).is_integer():
        return f"{v:.0f}"
    return f"{v:.1f}" if a >= 1 else f"{v:.2f}"


def _log_ticks(ax: plt.Axes, lo: float, hi: float) -> None:
    """Ticks of a log1p axis, labeled in the original unit."""
    candidates = [0, 1, 3, 10, 30, 100, 300, 1_000, 3_000, 10_000, 30_000, 100_000, 300_000, 1_000_000]
    ticks = [c for c in candidates if lo - 1e-9 <= np.log1p(c) <= hi + 1e-9]
    if len(ticks) > 7:
        ticks = ticks[::2]
    ax.set_xticks([np.log1p(c) for c in ticks])
    ax.set_xticklabels([_fmt(c) for c in ticks])


def _values(feats: pd.DataFrame, feature: str) -> np.ndarray:
    return pd.to_numeric(feats[feature], errors="coerce").to_numpy(float)


def plot_feature(feature: str, competition: pd.DataFrame, bank: pd.DataFrame, path: str | Path) -> Path:
    """One chart: left, the distribution in each source (share of its rows); right, the competition's fraud rate along the feature."""
    comp, bnk = _values(competition, feature), _values(bank, feature)
    y = competition["label"].to_numpy(int)
    base_rate = float(y.mean()) if len(y) else 0.0
    pooled = np.concatenate([comp[~np.isnan(comp)], bnk[~np.isnan(bnk)]])
    fig, (ax_d, ax_r) = plt.subplots(1, 2, figsize=(11, 3.9), dpi=130, facecolor=SURFACE)
    for ax in (ax_d, ax_r):
        _style(ax)
    categorical = len(np.unique(pooled)) <= MAX_CATEGORIES if len(pooled) else True
    log_axis = feature in LOG_AXIS and not categorical

    if categorical:
        levels = np.unique(pooled) if len(pooled) else np.array([0.0])
        pos = np.arange(len(levels))
        for offset, values, color, name in ((-0.19, comp, COMPETITION_COLOR, "competition"), (0.19, bnk, BANK_COLOR, "bank")):
            known = values[~np.isnan(values)]
            share = [float((known == lv).mean()) * 100 if len(known) else 0.0 for lv in levels]
            ax_d.bar(pos + offset, share, width=0.34, color=color, label=SOURCE_LABELS[name])
        rates = [float(y[comp == lv].mean()) * 100 if (comp == lv).any() else np.nan for lv in levels]
        ax_r.bar(pos, rates, width=0.34, color=COMPETITION_COLOR)
        for ax in (ax_d, ax_r):
            ax.set_xticks(pos)
            ax.set_xticklabels([_fmt(lv) for lv in levels])
        ax_r.set_xlim(ax_d.get_xlim())
    else:
        t = np.log1p if log_axis else (lambda a: a)
        tp = t(np.clip(pooled, 0, None)) if log_axis else pooled
        lo, hi = (float(tp.min()), float(tp.max())) if log_axis else tuple(float(q) for q in np.quantile(tp, [0.005, 0.995]))
        if hi <= lo:
            hi = lo + 1.0
        edges = np.linspace(lo, hi, 31)
        for values, color, name in ((comp, COMPETITION_COLOR, "competition"), (bnk, BANK_COLOR, "bank")):
            known = values[~np.isnan(values)]
            known = np.clip(t(np.clip(known, 0, None)) if log_axis else known, lo, hi)
            share = np.histogram(known, bins=edges)[0] / max(len(known), 1) * 100
            ax_d.stairs(share, edges, color=color, linewidth=2, label=SOURCE_LABELS[name])
            ax_d.stairs(share, edges, color=color, fill=True, alpha=0.10)
        # Fraud rate by equal-count bins of the competition, drawn at each bin's median.
        known = ~np.isnan(comp)
        if known.sum() >= 20:
            bins = pd.qcut(pd.Series(comp[known]), 10, duplicates="drop")
            g = pd.DataFrame({"x": comp[known], "y": y[known], "b": bins.to_numpy()}).groupby("b", observed=True).agg(x=("x", "median"), rate=("y", "mean"))
            gx = np.clip(t(np.clip(g["x"].to_numpy(), 0, None)) if log_axis else g["x"].to_numpy(), lo, hi)
            ax_r.plot(gx, g["rate"].to_numpy() * 100, color=COMPETITION_COLOR, linewidth=2, marker="o", markersize=7,
                      markeredgecolor=SURFACE, markeredgewidth=2)
        for ax in (ax_d, ax_r):
            ax.set_xlim(lo, hi)
            if log_axis:
                _log_ticks(ax, lo, hi)

    ax_r.axhline(base_rate * 100, color=MUTED, linewidth=1)
    ax_r.annotate(f"all rows: {base_rate * 100:.1f} %", xy=(1.0, base_rate * 100), xycoords=("axes fraction", "data"), xytext=(-4, 4),
                  textcoords="offset points", ha="right", va="bottom", fontsize=8.5, color=INK_SECONDARY)
    ax_r.set_ylim(bottom=0)
    null_c, null_b = (float(np.isnan(v).mean()) * 100 if len(v) else 0.0 for v in (comp, bnk))
    scale = ", log scale" if log_axis else ""
    ax_d.set_title(f"Distribution, share of each source's rows (%){scale}", fontsize=10, color=INK_SECONDARY, loc="left")
    how = "by value" if categorical else "by tenth of the rows"
    ax_r.set_title(f"Observed fraud rate in the competition (%), {how}", fontsize=10, color=INK_SECONDARY, loc="left")
    ax_d.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY, loc="best")
    fig.suptitle(f"{feature}: {FEATURE_PHRASES.get(feature, feature)}", x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.text(0.01, 0.01, f"Nulls: competition {null_c:.1f} %, bank {null_b:.1f} % (left out of both panels).", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out


def plot_observed_vs_predicted(train_bins: list[dict[str, Any]], test_bins: list[dict[str, Any]], days: list[dict[str, Any]], path: str | Path) -> Path:
    """Left: predicted probability against observed fraud rate by score decile. Right: daily observed and expected frauds of the holdout."""
    fig, (ax_c, ax_t) = plt.subplots(1, 2, figsize=(11, 4.4), dpi=130, facecolor=SURFACE)
    for ax in (ax_c, ax_t):
        _style(ax)
    points = [b[k] for bins in (train_bins, test_bins) for b in bins for k in ("mean_predicted", "observed_rate") if b[k] > 0]
    lo, hi = min(points) * 0.7, max(points) * 1.4
    ax_c.plot([lo, hi], [lo, hi], color=MUTED, linewidth=1)
    ax_c.annotate("observed = predicted", xy=(hi * 0.3, hi * 0.3), xytext=(10, -10), textcoords="offset points", ha="left", va="top", fontsize=8.5,
                  color=INK_SECONDARY)
    for bins, color, name in ((train_bins, COMPETITION_COLOR, "Train"), (test_bins, BANK_COLOR, "Holdout (last 20 % of the days)")):
        ax_c.plot([b["mean_predicted"] for b in bins], [max(b["observed_rate"], lo) for b in bins], color=color, linewidth=2, marker="o",
                  markersize=7, markeredgecolor=SURFACE, markeredgewidth=2, label=name)
    ax_c.set_xscale("log")
    ax_c.set_yscale("log")
    ax_c.set_xlim(lo, hi)
    ax_c.set_ylim(lo, hi)
    ax_c.grid(axis="x", color=GRID, linewidth=1)
    ax_c.set_xlabel("Mean predicted probability of the score decile", fontsize=9, color=INK_SECONDARY)
    ax_c.set_title("Observed fraud rate by score decile (log scales)", fontsize=10, color=INK_SECONDARY, loc="left")
    ax_c.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY, loc="upper left")

    x = pd.to_datetime([d["day"] for d in days])
    ax_t.plot(x, [d["observed"] for d in days], color=BANK_COLOR, linewidth=2, label="Observed frauds")
    ax_t.plot(x, [d["expected"] for d in days], color=INK_SECONDARY, linewidth=2, label="Expected (sum of the predicted probabilities)")
    ax_t.set_ylim(bottom=0)
    ax_t.set_title("Holdout: frauds per day", fontsize=10, color=INK_SECONDARY, loc="left")
    ax_t.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY, loc="lower left")
    ax_t.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax_t.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.suptitle("Observed against predicted on the IEEE-CIS competition", x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return out


def run(competition: str | Path, lakehouse: str | Path, model_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    bundle = joblib.load(model_path)
    features, model = list(bundle["features"]), bundle["model"]
    assert features == list(DEPLOYABLE_V1), "the bundle was trained on another feature list"
    comp = build_contract_features(load_competition(competition))
    bank_all = build_contract_features(load_bank_canonical(lakehouse))
    bank = bank_all[bank_all["in_scope"]].reset_index(drop=True)

    is_test, days, split_at = holdout_mask(comp["ts"])
    scores = model.predict_proba(bundle["ranker_competition"].transform(comp[features]).to_numpy(float))[:, 1]
    y = comp["label"].to_numpy(int)
    test = is_test.to_numpy()
    train_bins, test_bins = calibration_table(y[~test], scores[~test]), calibration_table(y[test], scores[test])
    daily = daily_observed_expected(comp["ts"][test], y[test], scores[test])
    bank_scores = model.predict_proba(bundle["ranker"].transform(bank[features]).to_numpy(float))[:, 1]
    bank_bins = calibration_table(bank["label"].to_numpy(int), bank_scores)

    out = Path(out_dir)
    charts = out / "eda"
    names = {f: f"{i:02d}_{f}.png" for i, f in enumerate(features, start=1)}
    for f in features:
        plot_feature(f, comp, bank, charts / names[f])
    plot_observed_vs_predicted(train_bins, test_bins, daily, charts / "observed_vs_predicted.png")

    trained = bundle.get("report") or {}
    report = {
        "model": {"path": str(model_path), "trained_at": trained.get("run_at"), "commit": trained.get("commit"),
                  "contract_version": bundle.get("contract_version"), "threshold": float(bundle["threshold"]), "threshold_kind": bundle.get("threshold_kind")},
        "sources": {"competition": {"rows": int(len(comp)), "positives": int(y.sum()), "days": len(days), "holdout_from": str(split_at),
                                    "train_rows": int((~test).sum()), "holdout_rows": int(test.sum())},
                    "bank": {"rows": int(len(bank)), "is_fraud_flags": int(bank["label"].sum()), "anchor": bank_all.attrs.get("anchor"),
                             "window_days": 60, "channels": ["Web", "App"]}},
        "features": features, "charts": names,
        "stats": {"competition": feature_stats(comp, features, label="label"), "bank": feature_stats(bank, features)},
        "observed_vs_predicted": {"train": train_bins, "holdout": test_bins, "holdout_daily": daily,
                                  "holdout_observed": int(y[test].sum()), "holdout_expected": float(scores[test].sum()),
                                  "train_observed": int(y[~test].sum()), "train_expected": float(scores[~test].sum())},
        "bank_flags_by_score_decile": bank_bins,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "risk_feature_eda.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / "risk_feature_eda.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def _cell(v: Any) -> str:
    if v is None:
        return "none"
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    return f"{v:.2f}" if a >= 10 else f"{v:.3f}"


def render_markdown(r: dict[str, Any]) -> str:
    m, c, b = r["model"], r["sources"]["competition"], r["sources"]["bank"]
    lines = ["# Risk model: EDA of the 19 served features and observed against predicted", "",
             f"Bundle `{m['path']}` (trained {m['trained_at']}, commit {m['commit']}, contract v{m['contract_version']}, "
             f"threshold {m['threshold']:.4f}, {m['threshold_kind']}). Written by `src/ml/risk_feature_eda.py`.", "",
             "Sources:", "",
             f"- **IEEE-CIS competition** (external, Kaggle): {c['rows']:,} card-not-present transactions, {c['positives']:,} frauds "
             f"({c['positives'] / c['rows'] * 100:.2f} %), {c['days']} days. Train {c['train_rows']:,} rows; holdout {c['holdout_rows']:,} rows from {c['holdout_from']}.",
             f"- **Bank serving window** (`synthetic-organizer`, derived): {b['rows']:,} Web and App charges in the {b['window_days']} days to {b['anchor']}, "
             f"{b['is_fraud_flags']} `is_fraud` flags.", "",
             "Values are the raw features, before the per-source percentile ranks the model reads. Offline analysis, not a production result.", ""]
    for key, title, labeled in (("competition", "Features in the IEEE-CIS competition", True), ("bank", "Features in the bank serving window", False)):
        lines += [f"## {title}", ""]
        head = "| Feature | Nulls % | Min | Max | Mean | Median | Std |"
        lines += [head + (" Mean, fraud | Mean, not fraud |" if labeled else ""), "| --- | --- | --- | --- | --- | --- | --- |" + (" --- | --- |" if labeled else "")]
        for s in r["stats"][key]:
            row = f"| `{s['feature']}` | {s['null_share'] * 100:.1f} | {_cell(s['min'])} | {_cell(s['max'])} | {_cell(s['mean'])} | {_cell(s['median'])} | {_cell(s['std'])} |"
            lines.append(row + (f" {_cell(s['mean_label_1'])} | {_cell(s['mean_label_0'])} |" if labeled else ""))
        lines.append("")
    lines += ["## One chart per feature", "",
              "Left: the distribution in each source, as a share of its own rows. Right: the observed fraud rate of the competition along the feature "
              "(the bank has no usable label). Nulls are left out of both panels and counted under each chart.", ""]
    for f in r["features"]:
        lines += [f"### `{f}`", "", f"![{f}](eda/{r['charts'][f]})", ""]
    o = r["observed_vs_predicted"]
    lines += ["## Observed against predicted on the competition", "", "![Observed against predicted](eda/observed_vs_predicted.png)", "",
              f"Totals: train {o['train_observed']:,} observed against {o['train_expected']:,.0f} expected; "
              f"holdout {o['holdout_observed']:,} observed against {o['holdout_expected']:,.0f} expected.", ""]
    for key, title in (("train", "Train"), ("holdout", "Holdout")):
        lines += [f"### {title}, by score decile", "", "| Decile | Rows | Score range | Mean predicted % | Observed frauds | Observed % |", "| --- | --- | --- | --- | --- | --- |"]
        for x in o[key]:
            lines.append(f"| {x['bin']} | {x['n']:,} | {x['score_min']:.4f} to {x['score_max']:.4f} | {x['mean_predicted'] * 100:.2f} | {x['positives']:,} | {x['observed_rate'] * 100:.2f} |")
        lines.append("")
    lines += ["## Bank: `is_fraud` flags by score decile", "",
              "The bank label has no learnable signal, so this table is a check, not a validation: the flags should spread evenly.", "",
              "| Decile | Charges | Score range | Mean score % | `is_fraud` flags |", "| --- | --- | --- | --- | --- |"]
    for x in r["bank_flags_by_score_decile"]:
        lines.append(f"| {x['bin']} | {x['n']:,} | {x['score_min']:.4f} to {x['score_max']:.4f} | {x['mean_predicted'] * 100:.2f} | {x['positives']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="EDA of the served risk features and observed against predicted fraud on the IEEE-CIS competition")
    p.add_argument("--competition", default="data/kaggle")
    p.add_argument("--lakehouse", default="data/lakehouse_full.duckdb")
    p.add_argument("--model", default="models/fraud_risk_ieee.joblib")
    p.add_argument("--out", default="reports/ml")
    a = p.parse_args()
    r = run(a.competition, a.lakehouse, a.model, a.out)
    o = r["observed_vs_predicted"]
    print(f"{len(r['features'])} feature charts in {a.out}/eda; holdout frauds observed {o['holdout_observed']}, expected {o['holdout_expected']:.0f}")


if __name__ == "__main__":
    main()
