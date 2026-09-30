"""
Permutation importance of every IEEE-CIS column (transaction and identity tables) on a holdout time split.

Goal (team, 29-Sep): find the competition features worth cherry-picking into the deployed risk model, either as
questions the agent can ask the customer (Jev typed answers) or as bank-side data. Output: reports/ml/ieee_cis_feature_importance.json
and the markdown written from it. The competition files are git-ignored (data/kaggle).

    uv run python scripts/notebooks/ieee_cis_feature_importance.py --competition data/kaggle --out reports/ml
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

FAMILIES = {
    "amount and product": lambda c: c in ("TransactionAmt", "ProductCD", "amt_cents"),
    "time of day and week": lambda c: c in ("hour", "day_of_week"),
    "card (card1 to card6)": lambda c: c.startswith("card"),
    "billing address (addr1, addr2)": lambda c: c.startswith("addr"),
    "distances (dist1, dist2)": lambda c: c.startswith("dist"),
    "email domains (P, R)": lambda c: c.endswith("emaildomain"),
    "counts C1 to C14": lambda c: c.startswith("C") and c[1:].isdigit(),
    "time deltas D1 to D15": lambda c: c.startswith("D") and c[1:].isdigit(),
    "match flags M1 to M9": lambda c: c.startswith("M") and c[1:].isdigit(),
    "Vesta V1 to V339": lambda c: c.startswith("V") and c[1:].isdigit(),
    "identity numeric id_01 to id_11": lambda c: c.startswith("id_") and c[3:].isdigit() and int(c[3:]) <= 11,
    "identity categorical id_12 to id_38": lambda c: c.startswith("id_") and c[3:].isdigit() and int(c[3:]) >= 12,
    "device (DeviceType, DeviceInfo)": lambda c: c.startswith("Device"),
}


def family_of(col: str) -> str:
    for name, test in FAMILIES.items():
        if test(col):
            return name
    return "other"


def load(competition: Path, limit: int | None) -> pd.DataFrame:
    con = duckdb.connect()
    lim = f" LIMIT {int(limit)}" if limit else ""
    df = con.execute(f"""SELECT t.*, i.* EXCLUDE (TransactionID)
                         FROM read_csv_auto('{competition}/train_transaction.csv', sample_size=50000) t
                         LEFT JOIN read_csv_auto('{competition}/train_identity.csv', sample_size=50000) i USING (TransactionID)
                         ORDER BY t.TransactionDT{lim}""").df()
    con.close()
    return df


def encode(df: pd.DataFrame) -> tuple[np.ndarray, list[str], list[bool], dict[str, str]]:
    """Numeric as float32; categorical with at most 255 levels as codes (HGB categorical); wider ones as frequency."""
    df = df.copy()
    df["hour"] = (df["TransactionDT"] // 3600) % 24
    df["day_of_week"] = (df["TransactionDT"] // 86400) % 7
    df["amt_cents"] = ((df["TransactionAmt"] * 100).round() % 100 != 0).astype(int)
    drop = ["TransactionID", "isFraud", "TransactionDT"]  # the raw clock would only encode the calendar trend
    cols, is_cat, encoding, mats = [], [], {}, []
    for c in df.columns:
        if c in drop:
            continue
        s = df[c]
        if s.dtype == object or s.dtype == bool or str(s.dtype) == "boolean":
            s = s.astype(object).where(s.notna(), None)
            n = s.nunique(dropna=True)
            if n <= 255:
                codes, _ = pd.factorize(s, use_na_sentinel=True)
                x = np.where(codes < 0, np.nan, codes).astype(np.float32)
                encoding[c] = f"categorical ({n} levels)"
                is_cat.append(True)
            else:
                freq = s.map(s.value_counts(normalize=True))
                x = pd.to_numeric(freq, errors="coerce").to_numpy(np.float32)
                encoding[c] = f"frequency ({n} levels)"
                is_cat.append(False)
        else:
            x = pd.to_numeric(s, errors="coerce").to_numpy(np.float32)
            encoding[c] = "numeric"
            is_cat.append(False)
        cols.append(c)
        mats.append(x)
    return np.column_stack(mats), cols, is_cat, encoding


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--competition", default="data/kaggle")
    p.add_argument("--out", default="reports/ml")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--perm-rows", type=int, default=80000)
    a = p.parse_args()
    t0 = time.time()
    df = load(Path(a.competition), a.limit)
    y = df["isFraud"].to_numpy(int)
    X, cols, is_cat, encoding = encode(df)
    day = (df["TransactionDT"] // 86400).to_numpy()
    days = np.unique(day)
    split_day = days[int(round(len(days) * 0.8))]
    tr, te = day < split_day, day >= split_day
    # HGB binning needs at least two distinct non-null values in the training rows.
    keep = [j for j in range(X.shape[1]) if (~np.isnan(X[tr, j])).sum() >= 1000 and len(np.unique(X[tr, j][~np.isnan(X[tr, j])])) >= 2]  # binning subsamples 200k rows
    dropped = [cols[j] for j in range(X.shape[1]) if j not in keep]
    X, cols, is_cat = X[:, keep], [cols[j] for j in keep], [is_cat[j] for j in keep]
    print(f"rows {len(df):,}, columns {len(cols)} (dropped {len(dropped)} constant or null in train), train {tr.sum():,}, holdout {te.sum():,}, loaded and encoded in {time.time() - t0:.0f}s", flush=True)
    model = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=63, min_samples_leaf=40,
                                           categorical_features=is_cat, early_stopping=True, validation_fraction=0.1, random_state=7)
    model.fit(X[tr], y[tr])
    s_te = model.predict_proba(X[te])[:, 1]
    auc_full = roc_auc_score(y[te], s_te)
    print(f"holdout ROC AUC with every column: {auc_full:.4f} ({model.n_iter_} iterations, {time.time() - t0:.0f}s)", flush=True)

    rng = np.random.default_rng(7)
    idx = np.flatnonzero(te)
    if len(idx) > a.perm_rows:
        idx = rng.choice(idx, a.perm_rows, replace=False)
    Xp, yp = X[idx].copy(), y[idx]
    base = roc_auc_score(yp, model.predict_proba(Xp)[:, 1])
    per_feature = {}
    for j, c in enumerate(cols):
        saved = Xp[:, j].copy()
        Xp[:, j] = rng.permutation(saved)
        per_feature[c] = float(base - roc_auc_score(yp, model.predict_proba(Xp)[:, 1]))
        Xp[:, j] = saved
    print(f"per-feature permutation done ({time.time() - t0:.0f}s)", flush=True)
    per_family = {}
    for fam in list(FAMILIES) + ["other"]:
        js = [j for j, c in enumerate(cols) if family_of(c) == fam]
        if not js:
            continue
        saved = Xp[:, js].copy()
        for j in js:
            Xp[:, j] = rng.permutation(Xp[:, j])
        per_family[fam] = {"columns": len(js), "auc_drop": float(base - roc_auc_score(yp, model.predict_proba(Xp)[:, 1]))}
        Xp[:, js] = saved
    null_pct = {c: float(np.isnan(X[:, j]).mean() * 100) for j, c in enumerate(cols)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"rows": int(len(df)), "columns": len(cols), "holdout_rows": int(te.sum()), "holdout_auc_all_columns": float(auc_full),
              "permutation_rows": int(len(idx)), "permutation_base_auc": float(base), "iterations": int(model.n_iter_),
              "per_feature": dict(sorted(per_feature.items(), key=lambda kv: -kv[1])), "per_family": dict(sorted(per_family.items(), key=lambda kv: -kv[1]["auc_drop"])),
              "encoding": encoding, "null_pct": null_pct, "dropped_constant_in_train": dropped, "family_of": {c: family_of(c) for c in cols}, "seconds": int(time.time() - t0)}
    (out / "ieee_cis_feature_importance.json").write_text(json.dumps(result, indent=1))
    print(f"written {out / 'ieee_cis_feature_importance.json'} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
