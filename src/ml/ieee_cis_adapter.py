"""
IEEE-CIS Fraud Detection (Kaggle, Vesta) columns to the canonical frame of the feature contract (spec section 3).

The client id is the first-place recipe: card1, addr1 and the normalized D1 (the day the card started). DuckDB reads
the T/F match flags as booleans, so the flags accept booleans and strings; M4 holds codes (M0, M1, M2) and is not a flag.
The files live in data/kaggle/ (git-ignored, competition licence: non-commercial use, no redistribution).
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ORIGIN = "2017-12-01"  # TransactionDT is seconds from a reference instant; the exact origin does not matter for time-of-day patterns
COMPETITION_COLUMNS = ["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "card1", "card6", "addr1", "dist1", "D1",
                       "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]
MATCH_FLAGS = ["M1", "M2", "M3", "M5", "M6", "M7", "M8", "M9"]
_FLAG = {True: 1.0, "T": 1.0, "True": 1.0, "true": 1.0, False: 0.0, "F": 0.0, "False": 0.0, "false": 0.0}


def _flag(series: pd.Series) -> pd.Series:
    return series.map(lambda v: _FLAG.get(v, np.nan) if not (isinstance(v, float) and np.isnan(v)) else np.nan).astype(float)


def competition_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    day = (pd.to_numeric(df["TransactionDT"]) // 86400).astype(int)
    d1 = pd.to_numeric(df["D1"], errors="coerce").fillna(-9999)
    addr = pd.to_numeric(df["addr1"], errors="coerce").fillna(-1).astype(int)
    uid = df["card1"].astype(str) + "_" + addr.astype(str) + "_" + (day - d1).astype(int).astype(str)
    kind = pd.Series([str(v).lower() if isinstance(v, str) and str(v).lower() in ("credit", "debit") else None for v in df["card6"]], index=df.index, dtype=object)
    dist = pd.to_numeric(df["dist1"], errors="coerce")
    bucket = np.select([dist.isna(), dist == 0, dist <= 50], [np.nan, 0, 1], 2)
    flags = pd.concat([_flag(df[c]) for c in MATCH_FLAGS if c in df.columns], axis=1)
    consistency = flags.mean(axis=1, skipna=True).where(flags.notna().any(axis=1), np.nan)
    return pd.DataFrame({
        "row_id": df["TransactionID"].astype(str), "uid": uid, "customer_uid": uid,
        "ts": pd.Timestamp(ORIGIN) + pd.to_timedelta(pd.to_numeric(df["TransactionDT"]), unit="s"),
        "amount_usd": pd.to_numeric(df["TransactionAmt"], errors="coerce"), "amount_local": pd.to_numeric(df["TransactionAmt"], errors="coerce"),
        "card_kind": kind, "card_age_days": pd.to_numeric(df["D1"], errors="coerce"), "address_distance_bucket": bucket,
        "consistency_matches": consistency, "label": pd.to_numeric(df["isFraud"], errors="coerce").fillna(0).astype(int),
    })


def load_competition(path: str | Path, limit: int | None = None) -> pd.DataFrame:
    """train_transaction.csv (or the folder holding it) read through DuckDB with the needed columns only."""
    p = Path(path)
    csv = p / "train_transaction.csv" if p.is_dir() else p
    if not csv.exists():
        raise FileNotFoundError(f"competition file not found: {csv}")
    con = duckdb.connect()
    cols = ", ".join(COMPETITION_COLUMNS)
    lim = f" LIMIT {int(limit)}" if limit else ""
    df = con.execute(f"SELECT {cols} FROM read_csv_auto('{csv}', sample_size=50000) ORDER BY TransactionDT{lim}").df()
    con.close()
    return competition_to_canonical(df)
