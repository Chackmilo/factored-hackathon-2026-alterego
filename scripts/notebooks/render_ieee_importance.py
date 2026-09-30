"""
Markdown report from reports/ml/ieee_cis_feature_importance.json: per-family and per-feature importance, the meaning of
each top column (official from Vesta where disclosed, community readings marked as such) and the way to obtain it at
deploy: already in the contract, askable in the chat (Jev typed answers), bank-side data, or unavailable.

    uv run python scripts/notebooks/render_ieee_importance.py --json reports/ml/ieee_cis_feature_importance.json --out reports/ml/ieee_cis_feature_importance.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

IN_CONTRACT = "already in the contract"
CHAT = "askable in the chat (Jev typed answer)"
BANK = "bank-side data (gateway or lakehouse)"
NONE = "unavailable (anonymized or undisclosed)"

MEANINGS = {
    "TransactionAmt": ("Amount in USD (official)", IN_CONTRACT, "amount_usd, log_amount_usd"),
    "amt_cents": ("Whether the amount has cents (derived)", IN_CONTRACT, "amount_has_cents"),
    "hour": ("Hour of the transaction (derived from TransactionDT)", IN_CONTRACT, "hour_sin, hour_cos"),
    "day_of_week": ("Day of the week (derived)", IN_CONTRACT, "day_of_week"),
    "ProductCD": ("Product code of the purchase, W, H, C, S, R (official, meaning undisclosed)", NONE, "Jev found no bank equivalent (notebook 05)"),
    "card1": ("Card identifier (official: card information; community: the card number family)", BANK, "our product_id is the card: per-card aggregates already use it"),
    "card2": ("Card information (official; undisclosed)", BANK, "issuer-side attribute; we are the issuer, so any card attribute in bank.products applies (product currency, credit limit)"),
    "card3": ("Card information (official; community: issuing country)", BANK, "customer country from bank.customers (address bucket already compares it)"),
    "card4": ("Card network: visa, mastercard, amex, discover (official)", NONE, "no network column; Jev found no equivalent"),
    "card5": ("Card information (official; community: issuing bank)", NONE, "single issuer here"),
    "card6": ("Credit or debit (official)", IN_CONTRACT, "card_kind_credit, card_kind_debit"),
    "addr1": ("Billing region (official)", BANK, "customer city in bank.customers, compared through address_distance_bucket"),
    "addr2": ("Billing country (official)", BANK, "customer country; address_distance_bucket"),
    "dist1": ("Distance between billing, mailing, zip, IP or phone area (official, unspecified pair)", CHAT, "ask where the customer was when the charge happened, or whether the address on file is current; the bucket is in the contract"),
    "dist2": ("Second distance of the same kind (official)", CHAT, "same question; a second distance would need the merchant location"),
    "P_emaildomain": ("Purchaser email domain (official)", BANK, "customer email domain in bank.customers (uniform in this dataset, dropped from the contract)"),
    "R_emaildomain": ("Recipient email domain (official)", CHAT, "for transfers: ask whether the customer knows the recipient; the bank has no recipient field"),
    "DeviceType": ("desktop or mobile (official)", CHAT, "ask which device the customer normally uses for the app or the web; digital_events cannot be tied to a charge"),
    "DeviceInfo": ("Device model or browser string (official)", BANK, "app telemetry at login, not in the serving copy today"),
    "id_30": ("Operating system of the session (official)", CHAT, "same as DeviceType: ask, or capture at login"),
    "id_31": ("Browser of the session (official)", BANK, "capture at login; Jev homologated the browser families"),
    "id_33": ("Screen resolution (official)", BANK, "app telemetry"),
}
FAMILY_MEANING = {
    "C": ("Counts: how many addresses, emails or phones are associated with the card (official, masked)", BANK,
          "the bank knows the customer's cards, addresses and contacts: distinct products per customer, distinct cities per card, distinct merchants per card over the history"),
    "D": ("Time deltas in days, for example since the previous transaction or since the card started (official)", IN_CONTRACT,
          "days_since_prev_tx_card and card age (card age excluded as non-deployable); D4, D10, D15 are community-read as days since the first transaction with this address or device: computable from the bank history"),
    "M": ("Match flags, for example names on the card and on the address (official)", CHAT,
          "consistency_matches covers country, city and currency; the name and address matches are askable: is the address on file current, is the card in your name"),
    "V": ("Vesta engineered features: ranking, counting and entity relations (official, undisclosed)", NONE,
          "not reproducible as such; the bank-side counting features (C and D families) are the reachable part"),
    "id_num": ("Identity numeric scores: network connection and device ratings (official, undisclosed)", BANK, "IP reputation and device risk from the login telemetry, not in the serving copy"),
    "id_cat": ("Identity categorical: browser, OS, screen, proxy flags, match statuses (official; id_23 is proxy type, id_34 a match status)", BANK, "login telemetry; the proxy and match flags are bank-side"),
}


def describe(col: str) -> tuple[str, str, str]:
    if col in MEANINGS:
        return MEANINGS[col]
    m = re.match(r"^([CDMV])(\d+)$", col)
    if m:
        return FAMILY_MEANING[m.group(1)]
    m = re.match(r"^id_(\d+)$", col)
    if m:
        return FAMILY_MEANING["id_num" if int(m.group(1)) <= 11 else "id_cat"]
    return ("undisclosed", NONE, "")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--json", default="reports/ml/ieee_cis_feature_importance.json")
    p.add_argument("--out", default="reports/ml/ieee_cis_feature_importance.md")
    p.add_argument("--top", type=int, default=40)
    a = p.parse_args()
    r = json.loads(Path(a.json).read_text())
    pf, fam = r["per_feature"], r["per_family"]
    lines = ["# IEEE-CIS feature importance: what is worth bringing into the deployed risk model", "",
             f"Model: gradient boosting on every competition column ({r['columns']} after encoding; {len(r.get('dropped_constant_in_train', []))} dropped as constant in the training days), "
             f"time split with the last 20% of the days held out ({r['holdout_rows']:,} rows). Holdout ROC AUC with every column: **{r['holdout_auc_all_columns']:.4f}** "
             f"(the deployable 19-feature transfer model sits at 0.817). Importance is the ROC AUC lost when the column is shuffled on {r['permutation_rows']:,} holdout rows "
             f"(base {r['permutation_base_auc']:.4f}); families are shuffled as a block, which is what matters for cherry-picking. Run time {r['seconds']} s.", "",
             "Only column names and aggregate numbers appear here; the competition rows stay in `data/kaggle/` (git-ignored, non-commercial licence).", "",
             "## 1. Importance by column family (shuffled as a block)", "", "| Family | Columns | AUC lost | How we could get it at deploy |", "| --- | --- | --- | --- |"]
    fam_path = {"amount and product": "amount is in the contract; the product code has no equivalent", "time of day and week": "in the contract",
                "card (card1 to card6)": "card id and credit or debit are in the contract; issuer attributes are ours by definition", "billing address (addr1, addr2)": "customer city and country, in the address bucket",
                "distances (dist1, dist2)": "bucket in the contract; the exact distance needs the customer's location or the merchant's", "email domains (P, R)": "purchaser domain is bank-side and uniform here; recipient is askable",
                "counts C1 to C14": "bank-side counts of products, cities and merchants per card", "time deltas D1 to D15": "days since the previous charge is in the contract; the rest is bank history",
                "match flags M1 to M9": "consistency is in the contract; name and address matches are askable", "Vesta V1 to V339": "unavailable as such",
                "identity numeric id_01 to id_11": "login telemetry, not in the serving copy", "identity categorical id_12 to id_38": "login telemetry or askable (device, OS)",
                "device (DeviceType, DeviceInfo)": "askable, or captured at login"}
    for name, v in fam.items():
        lines.append(f"| {name} | {v['columns']} | {v['auc_drop']:.4f} | {fam_path.get(name, '')} |")
    lines += ["", f"## 2. Top {a.top} columns", "", "| Rank | Column | AUC lost | Null % | Meaning | Deploy path | How |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for i, (c, v) in enumerate(list(pf.items())[:a.top], 1):
        meaning, path, how = describe(c)
        lines.append(f"| {i} | `{c}` | {v:.4f} | {r['null_pct'][c]:.0f} | {meaning} | {path} | {how} |")
    # cherry-pick summary by deploy path over the top 60
    buckets: dict[str, list[str]] = {IN_CONTRACT: [], CHAT: [], BANK: [], NONE: []}
    for c, v in list(pf.items())[:60]:
        buckets[describe(c)[1]].append(f"`{c}` ({v:.4f})")
    lines += ["", "## 3. Cherry-pick: the top 60 columns by the way we can obtain them", ""]
    for k, cols in buckets.items():
        lines.append(f"- **{k}** ({len(cols)}): {', '.join(cols) if cols else 'none'}")
    lines += ["", "## 4. Recommendation for the conversation and the tools", "",
              "1. **Questions Jev can type during the dispute** (each becomes a feature with a calibrated probability, never a decision): is the card with you now; is the address on file where you live today; were you in the city of the charge that day; which device do you use for the app or the web; for a transfer, do you know the recipient; did you make other purchases with this card that day. They stand in for the match flags (M), the distances (dist) and the device and recipient columns.",
              "2. **Bank-side counting features to add to the contract** (the C and D families, the reachable part of the Vesta recipe): distinct products per customer, distinct cities and merchants per card over the history, days since the first charge in this city, share of the card's charges on this channel. They come from the customer's own rows in the serving copy.",
              "3. **Login telemetry** (device, OS, browser, IP country, proxy) is the identity table's counterpart; it is worth capturing at login in the app so the next model version can use it, since digital_events cannot be tied to a charge today.",
              f"4. **Where the gain is**: the family table says the largest block is the C counts ({fam.get('counts C1 to C14', {}).get('auc_drop', 0):.3f} AUC when shuffled), ahead of the 339 Vesta columns ({fam.get('Vesta V1 to V339', {}).get('auc_drop', 0):.3f}), the D deltas ({fam.get('time deltas D1 to D15', {}).get('auc_drop', 0):.3f}) and the card attributes ({fam.get('card (card1 to card6)', {}).get('auc_drop', 0):.3f}). The counts and the deltas are bank-side history, so most of the distance between the deployable model (0.817) and the all-column one ({r['holdout_auc_all_columns']:.3f}) is reachable without the anonymized columns.",
              "5. **Out of reach**: the Vesta V columns as such and the product code."]
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"written {a.out}")


if __name__ == "__main__":
    main()
