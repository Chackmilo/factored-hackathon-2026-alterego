"""Serving subset: pure rules always, and the full publish plus live views against Postgres when TEST_DATABASE_URL is set."""
import os
from datetime import date

import pytest

from src.data.publish_serving import (
    PublishError,
    extract,
    fill_amount_usd,
    normalize_country,
    publish,
)
from src.eval.fixture_bank import build_bank_fixture
from src.ops.store import OpsStore


def test_country_and_amount_rules():
    assert normalize_country("Mexico") == "México" and normalize_country("Colombia") == "Colombia"
    assert fill_amount_usd(80.0, "USD", None, None) == (80.0, "same_currency")
    assert fill_amount_usd(324599.21, "COP", 81.15, 0.000248) == (81.15, "native")
    assert fill_amount_usd(608000.0, "COP", None, 0.000248) == (150.78, "daily_rate_fill")
    with pytest.raises(PublishError):
        fill_amount_usd(1000.0, "ARS", None, None)


def test_extract_from_a_fixture_quarantines_orphans(tmp_path):
    bank = build_bank_fixture(tmp_path / "bank.duckdb",
                              [{"customer_id": "CLI-P1", "segment": "Plus", "country": "Mexico", "account_age_days": 300}],
                              [{"product_id": "PRD-P1", "customer_id": "CLI-P1"}, {"product_id": "PRD-GHOST", "customer_id": "CLI-GHOST"}],
                              [{"transaction_id": "TRX-P1", "customer_id": "CLI-P1", "product_id": "PRD-P1", "process_date": "2026-06-10", "amount": 80.0, "merchant_name": "Oxxo"},
                               {"transaction_id": "TRX-GHOST", "customer_id": "CLI-GHOST", "product_id": "PRD-GHOST", "process_date": "2026-06-10", "amount": 5.0}])
    subset = extract(bank)
    assert [c[2] for c in subset["customers"]] == ["México"]
    assert subset["customers"][0][5] == date(2026, 6, 17).fromordinal(date(2026, 6, 17).toordinal() - 300)  # registration derived from the age
    assert len(subset["products"]) == 1 and len(subset["transactions"]) == 1
    assert subset["quarantine"] == {"products_orphan_customer": 1, "transactions_orphan_customer": 1, "complaints_orphan_customer": 0}
    assert subset["transactions"][0][9] == "same_currency"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_publish_to_postgres_meets_contracts_and_live_views(tmp_path):
    url = os.environ["TEST_DATABASE_URL"]
    OpsStore.apply_postgres_migration(url)
    bank = build_bank_fixture(tmp_path / "bank.duckdb",
                              [{"customer_id": "CLI-S1", "segment": "Plus", "country": "Colombia", "account_age_days": 250, "complaints_last_90d": 0}],
                              [{"product_id": "PRD-S1", "customer_id": "CLI-S1"}],
                              [{"transaction_id": "TRX-S1", "customer_id": "CLI-S1", "product_id": "PRD-S1", "process_date": "2026-06-10", "amount": 80.0, "merchant_name": "Oxxo"}])
    report = publish(url, bank)
    assert report["ok"] and report["counts"]["transactions"]["bank"] == 1 and report["forbidden_columns"] == []

    import psycopg
    store = OpsStore(url)
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("DELETE FROM ops.card_locks WHERE customer_id = 'CLI-S1'")
        con.execute("DELETE FROM ops.dispute_cases WHERE customer_id = 'CLI-S1'")
        facts = con.execute("SELECT account_age_days, complaints_last_90d, active_products FROM ops.v_customer_policy_facts WHERE customer_id = 'CLI-S1'").fetchone()
        assert facts == (250, 0, 1)
        assert con.execute("SELECT product_status FROM ops.v_product_status WHERE product_id = 'PRD-S1'").fetchone() == ("Active",)
        lock_id = store.insert_lock(conversation_id=None, customer_id="CLI-S1", product_id="PRD-S1", reason="STOLEN_CARD_CLAIM", status="offered")
        store.update_lock(lock_id, "locked", verified=True)
        assert con.execute("SELECT product_status, active_lock_id FROM ops.v_product_status WHERE product_id = 'PRD-S1'").fetchone() == ("Blocked", lock_id)
        store.insert_case(conversation_id=None, customer_id="CLI-S1", transaction_id="TRX-S1", product_id="PRD-S1",
                          case_values={"case_type": "Claim", "category": "Transactions", "subcategory": "Cargo no reconocido", "reception_channel": "App", "status": "Open"},
                          claimed_amount=80.0, currency="USD", amount_usd=80.0, cited_clauses=[], provisional_credit_candidate=False, provisional_credit_amount_usd=0.0)
        assert con.execute("SELECT complaints_last_90d, active_products FROM ops.v_customer_policy_facts WHERE customer_id = 'CLI-S1'").fetchone() == (1, 0)
