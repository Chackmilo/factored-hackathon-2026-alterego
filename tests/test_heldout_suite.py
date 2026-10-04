"""The frozen held-out suite (brief section 5): mix, languages, provenance, design labels and the recorded hash."""
import hashlib
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from src.eval.cases import load_cases

SUITE = Path("data/eval/heldout_cases.jsonl")
HASH = Path("data/eval/heldout_cases.sha256")
TODAY = date(2026, 6, 17)
BRIEF_MIX = {"normal_le_150": 35, "normal_150_500": 35, "ambiguous": 30, "out_of_window_or_unsupported": 25,
             "high_value_or_multi_charge": 35, "high_fraud_anomaly": 20, "adversarial_or_security": 25, "tool_or_db_failure": 20,
             "incorrect_or_missing_data": 15, "multilingual_ambiguity": 10}


@pytest.fixture(scope="module")
def cases():
    return load_cases(SUITE)


def _target(case):
    return next(t for t in case.transactions if t["transaction_id"] == case.target_transaction_id)


def test_the_suite_has_the_brief_mix_and_language_split(cases):
    assert len(cases) == 250
    assert Counter(c.category for c in cases) == BRIEF_MIX
    assert Counter(c.language for c in cases) == {"es": 150, "pt": 100}


def test_portuguese_is_team_generated_and_every_expectation_is_a_design_label(cases):
    assert all(c.provenance == "team-generated" for c in cases if c.language == "pt")
    assert {c.provenance for c in cases} <= {"derived", "team-generated", "synthetic-organizer"}
    assert all(c.label_source == "design" for c in cases)


def test_every_segment_and_country_is_present(cases):
    assert {c.customer["segment"] for c in cases} == {"Premium", "Plus", "Basic", "Student"}
    assert {c.customer["country"] for c in cases} == {"Colombia", "México", "Argentina"}


def test_normal_disputes_sit_in_their_band_in_window_with_the_credit_rule(cases):
    for case in (c for c in cases if c.category in ("normal_le_150", "normal_150_500")):
        t, customer, exp = _target(case), case.customer, case.expected
        assert t["transaction_status"] == "Approved" and t["transaction_type"] in ("Purchase", "Payment", "Withdrawal", "Transfer")
        assert 0 <= (TODAY - date.fromisoformat(t["process_date"])).days <= 60
        if case.category == "normal_le_150":
            assert 0 < t["amount_usd"] <= 150
            eligible = (customer["segment"] in ("Premium", "Plus") and customer["account_age_days"] > 180
                        and customer["complaints_last_90d"] == 0)
            assert exp["credit_candidate"] is eligible
        else:
            assert 150 < t["amount_usd"] <= 500 and exp["credit_candidate"] is False
        assert exp["final_outcome"] == "AUTONOMOUS_RESOLUTION" and exp["case_opened"] is True


def test_high_value_cases_dispute_more_than_500_usd_or_three_charges(cases):
    for case in (c for c in cases if c.category == "high_value_or_multi_charge"):
        assert case.expected["requires_human"] is True
        if case.expected["escalation_reason"] == "AMOUNT_EXCEEDS_500_USD":
            assert _target(case)["amount_usd"] > 500
        else:
            assert case.expected["escalation_reason"] == "MULTIPLE_CHARGES_48H" and len(case.messages) == 4


def test_security_and_failure_cases_carry_their_scenario(cases):
    security = [c for c in cases if c.category == "adversarial_or_security"]
    assert Counter(c.attack["kind"] for c in security if c.attack) == {"token": 6, "cross_customer": 6}
    assert all(c.expected["final_outcome"] == "REJECTED" for c in security if c.attack)
    failures = [c for c in cases if c.category == "tool_or_db_failure"]
    assert all(c.fault and c.expected["requires_human"] for c in failures)


def test_the_builder_reads_a_relabeled_gold_in_the_vocabulary_the_suite_was_frozen_with(tmp_path):
    """Suite v1 was frozen when gold wrote "Unknown Merchant" for every charge without a merchant; a rebuilt gold must reproduce the same file."""
    import duckdb

    from src.eval.heldout import Bank, has_merchant

    path = tmp_path / "lakehouse.duckdb"  # team-generated fixture with the columns the builder reads
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE gold_customers (customer_id VARCHAR, segment VARCHAR, country VARCHAR, account_age_days INTEGER, complaints_last_90d INTEGER)")
    con.execute("INSERT INTO gold_customers VALUES ('C1', 'Plus', 'Colombia', 400, 0)")
    con.execute("""CREATE TABLE gold_transactions (transaction_id VARCHAR, customer_id VARCHAR, product_id VARCHAR, transaction_date TIMESTAMP,
        process_date DATE, transaction_type VARCHAR, transaction_status VARCHAR, amount DOUBLE, currency VARCHAR, amount_usd DOUBLE,
        amount_usd_source VARCHAR, merchant_name VARCHAR, merchant_category VARCHAR, channel VARCHAR, transaction_country VARCHAR)""")
    con.execute("""INSERT INTO gold_transactions VALUES
        ('T-WITHDRAWAL', 'C1', 'P1', TIMESTAMP '2026-06-10 12:00:00', DATE '2026-06-10', 'Withdrawal', 'Approved', 50.0, 'USD', 50.0, 'same_currency', 'Not Applicable', NULL, 'ATM', 'Colombia'),
        ('T-PURCHASE-GAP', 'C1', 'P1', TIMESTAMP '2026-06-11 12:00:00', DATE '2026-06-11', 'Purchase', 'Approved', 60.0, 'USD', 60.0, 'same_currency', 'Unknown Merchant', NULL, 'POS', 'Colombia'),
        ('T-PURCHASE', 'C1', 'P1', TIMESTAMP '2026-06-12 12:00:00', DATE '2026-06-12', 'Purchase', 'Approved', 70.0, 'USD', 70.0, 'same_currency', 'Oxxo', 'Food', 'POS', 'Colombia')""")
    con.execute("CREATE TABLE silver_products (product_id VARCHAR, customer_id VARCHAR, product_type VARCHAR, product_status VARCHAR)")
    con.close()
    charges = {t["transaction_id"]: t for t in Bank(path).charges["C1"]}
    assert charges["T-WITHDRAWAL"]["merchant_name"] == "Unknown Merchant" and not has_merchant(charges["T-WITHDRAWAL"])
    assert charges["T-PURCHASE-GAP"]["merchant_name"] == "Unknown Merchant" and not has_merchant(charges["T-PURCHASE-GAP"])
    assert charges["T-PURCHASE"]["merchant_name"] == "Oxxo" and has_merchant(charges["T-PURCHASE"])


def test_the_recorded_hash_matches_the_frozen_file():
    digest = hashlib.sha256(SUITE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert HASH.read_text().split()[0] == digest
