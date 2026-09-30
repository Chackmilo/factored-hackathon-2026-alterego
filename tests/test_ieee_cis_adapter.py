"""The competition columns map to the canonical frame the contract builder expects (spec section 3)."""
import numpy as np
import pandas as pd

from src.ml.ieee_cis_adapter import COMPETITION_COLUMNS, ORIGIN, competition_to_canonical


def competition_frame():
    return pd.DataFrame({
        "TransactionID": [1, 2, 3, 4], "isFraud": [0, 1, 0, 0], "TransactionDT": [86400, 90000, 2 * 86400, 3 * 86400 + 3600],
        "TransactionAmt": [50.0, 120.5, 30.0, 400.0], "card1": [1111, 1111, 2222, 1111], "card6": ["credit", "credit", "debit", None],
        "addr1": [300.0, 300.0, np.nan, 300.0], "dist1": [0.0, 120.0, np.nan, 10.0], "D1": [0.0, 0.0, 5.0, 2.0],
        "M1": [True, "T", False, None], "M2": [True, "F", None, None], "M3": [False, "F", None, None], "M4": ["M0", "M1", "M2", None],
        "M5": [None, None, None, None], "M6": [True, "T", True, None], "M7": [None, None, None, None], "M8": [None, None, None, None], "M9": [None, None, None, None],
    })


def test_canonical_columns_uid_and_time():
    c = competition_to_canonical(competition_frame())
    assert {"row_id", "uid", "customer_uid", "ts", "amount_usd", "amount_local", "card_kind", "card_age_days", "address_distance_bucket", "consistency_matches", "label"} <= set(c.columns)
    assert c.loc[0, "uid"] == c.loc[1, "uid"] == c.loc[3, "uid"] and c.loc[2, "uid"] != c.loc[0, "uid"]  # card1, addr1 and the card start day (day - D1)
    assert c.loc[0, "ts"] == pd.Timestamp(ORIGIN) + pd.Timedelta(seconds=86400)
    assert c["customer_uid"].equals(c["uid"])


def test_card_kind_distance_and_match_flags_survive_boolean_parsing():
    c = competition_to_canonical(competition_frame())
    assert c["card_kind"].tolist() == ["credit", "credit", "debit", None]
    assert c["address_distance_bucket"].tolist()[:2] == [0, 2] and np.isnan(c.loc[2, "address_distance_bucket"]) and c.loc[3, "address_distance_bucket"] == 1
    assert c.loc[0, "consistency_matches"] == 0.75  # M1 T, M2 T, M3 F, M6 T; M4 is a code, not a flag
    assert c.loc[1, "consistency_matches"] == 0.5
    assert np.isnan(c.loc[3, "consistency_matches"])
    assert c["label"].tolist() == [0, 1, 0, 0]
    assert "isFraud" in COMPETITION_COLUMNS and "M4" in COMPETITION_COLUMNS
