"""The whole dispute stack on Postgres: bank serving copy, ops schema, live views. Runs when TEST_DATABASE_URL is set."""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")


@pytest.fixture
def pg_stack(tmp_path):
    import psycopg

    from src.data.publish_serving import publish
    from src.eval.fixture_bank import build_bank_fixture
    from src.ops.store import OpsStore
    from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
    from src.tools.gateway_postgres import PostgresBankingGateway

    url = os.environ["TEST_DATABASE_URL"]
    OpsStore.apply_postgres_migration(url)
    bank = build_bank_fixture(tmp_path / "bank.duckdb",
                              [{"customer_id": "CLI-PG-1", "segment": "Plus", "country": "Colombia", "city": "Bogotá", "account_age_days": 250, "complaints_last_90d": 0},
                               {"customer_id": "CLI-PG-2", "segment": "Basic", "country": "Argentina", "account_age_days": 90, "complaints_last_90d": 1}],
                              [{"product_id": "PRD-PG-1", "customer_id": "CLI-PG-1", "currency": "COP"}, {"product_id": "PRD-PG-2", "customer_id": "CLI-PG-2"},
                               {"product_id": "PRD-PG-ACC", "customer_id": "CLI-PG-2", "product_type": "Cuenta Ahorros"},
                               {"product_id": "PRD-PG-OFF", "customer_id": "CLI-PG-2", "product_status": "Cancelled"}],
                              [{"transaction_id": "TRX-PG-1", "customer_id": "CLI-PG-1", "product_id": "PRD-PG-1", "process_date": "2026-06-10", "amount": 80.0, "merchant_name": "Oxxo",
                                "channel": "Web", "transaction_country": "USA", "transaction_city": "Miami"},
                               {"transaction_id": "TRX-PG-2", "customer_id": "CLI-PG-2", "product_id": "PRD-PG-2", "process_date": "2026-06-12", "amount": 50.0, "merchant_name": "Oxxo"}])
    publish(url, bank)
    with psycopg.connect(url, autocommit=True) as con:
        con.execute("DELETE FROM ops.messages WHERE conversation_id IN (SELECT conversation_id FROM ops.conversations WHERE customer_id IN ('CLI-PG-1', 'CLI-PG-2'))")
        for table in ("handoffs", "card_locks", "dispute_cases", "conversations"):
            con.execute(f"DELETE FROM ops.{table} WHERE customer_id IN ('CLI-PG-1', 'CLI-PG-2')")
    return DisputeOrchestrator(gateway=PostgresBankingGateway(url), ops=OpsStore(url)), url


def test_postgres_gateway_reads_bank_and_live_views(pg_stack):
    from tests.conftest import make_session
    orchestrator, _ = pg_stack
    session = make_session("CLI-PG-1")
    profile = orchestrator.gateway.get_customer_profile(session)
    assert profile["account_age_days"] == 250 and profile["complaints_last_90d"] == 0 and profile["complaints_include_ops_cases"] is True
    [row] = orchestrator.gateway.search_customer_transactions(session)
    assert row["transaction_id"] == "TRX-PG-1" and row["merchant_name_raw"] == "Oxxo" and row["is_within_60_days"] is True
    assert orchestrator.gateway.list_customer_cards(session) == [{"product_id": "PRD-PG-1", "product_type": "Tarjeta Crédito", "product_status": "Active"}]
    assert orchestrator.gateway.sample_customers()[0]["customer_id"] == "CLI-PG-1"


def test_postgres_stack_opens_case_and_locks_card_with_read_back(pg_stack):
    import psycopg

    from tests.conftest import make_session
    orchestrator, url = pg_stack
    session = make_session("CLI-PG-1")
    cid = orchestrator.start_conversation(session)["conversation_id"]
    first = orchestrator.handle_message(session, cid, "Me robaron la tarjeta y no reconozco un cargo de 80 dólares en Oxxo")
    assert first.case_id and first.lock_offer["product_id"] == "PRD-PG-1"
    second = orchestrator.handle_message(session, cid, "Sí")
    assert second.lock_status == "locked"
    with psycopg.connect(url, autocommit=True) as con:
        assert con.execute("SELECT product_status FROM ops.v_product_status WHERE product_id = 'PRD-PG-1'").fetchone() == ("Blocked",)
        assert con.execute("SELECT product_status FROM bank.products WHERE product_id = 'PRD-PG-1'").fetchone() == ("Active",)  # bank untouched
        assert con.execute("SELECT complaints_last_90d FROM ops.v_customer_policy_facts WHERE customer_id = 'CLI-PG-1'").fetchone() == (1,)
    # the live view now counts the case: a second small charge would no longer be a credit candidate
    assert orchestrator.gateway.get_customer_profile(session)["complaints_last_90d"] == 1


def test_postgres_lock_without_an_offer_keeps_its_reason_code(pg_stack):
    import psycopg

    from tests.conftest import make_session
    orchestrator, url = pg_stack
    result = orchestrator.gateway.execute_lock_card(make_session("CLI-PG-1"), "PRD-PG-1", reason_code="MULTI_CHARGE_FRAUD")
    with psycopg.connect(url, autocommit=True) as con:
        assert con.execute("SELECT reason FROM ops.card_locks WHERE lock_id = %s", [result["lock_id"]]).fetchone() == ("MULTI_CHARGE_FRAUD",)


def test_postgres_lock_with_an_unknown_reason_code_writes_nothing(pg_stack):
    import psycopg

    from tests.conftest import make_session
    orchestrator, url = pg_stack
    with pytest.raises(ValueError):
        orchestrator.gateway.execute_lock_card(make_session("CLI-PG-1"), "PRD-PG-1", reason_code="Preventive hold")
    with psycopg.connect(url, autocommit=True) as con:
        assert con.execute("SELECT count(*) FROM ops.card_locks WHERE product_id = 'PRD-PG-1'").fetchone() == (0,)


def test_postgres_gateway_rejects_other_customers_card(pg_stack):
    from src.tools.gateway import UnauthorizedAccessError
    from tests.conftest import make_session
    orchestrator, _ = pg_stack
    with pytest.raises(UnauthorizedAccessError):
        orchestrator.gateway.execute_lock_card(make_session("CLI-PG-2"), "PRD-PG-1")


@pytest.mark.parametrize("product_id", ["PRD-PG-ACC", "PRD-PG-OFF"])
def test_postgres_lock_refuses_an_owned_product_that_is_not_an_active_card(pg_stack, product_id):
    """The lock enforces what the orchestrator offers (an active card), whoever calls it."""
    import psycopg

    from src.tools.gateway import ActionVerificationError
    from tests.conftest import make_session
    orchestrator, url = pg_stack
    with pytest.raises(ActionVerificationError):
        orchestrator.gateway.execute_lock_card(make_session("CLI-PG-2"), product_id)
    with psycopg.connect(url, autocommit=True) as con:
        assert con.execute("SELECT count(*) FROM ops.card_locks WHERE product_id = %s", [product_id]).fetchone() == (0,)


def test_postgres_lock_of_a_card_already_locked_writes_no_second_lock(pg_stack):
    import psycopg

    from src.tools.gateway import ActionVerificationError
    from tests.conftest import make_session
    orchestrator, url = pg_stack
    session = make_session("CLI-PG-1")
    orchestrator.gateway.execute_lock_card(session, "PRD-PG-1")
    with pytest.raises(ActionVerificationError):
        orchestrator.gateway.execute_lock_card(session, "PRD-PG-1")
    with psycopg.connect(url, autocommit=True) as con:
        assert con.execute("SELECT count(*) FROM ops.card_locks WHERE product_id = 'PRD-PG-1'").fetchone() == (1,)


def test_postgres_search_and_profile_carry_what_the_risk_model_reads(pg_stack):
    """AUD-27: the served features are read from bank, not imputed with the training median."""
    from tests.conftest import make_session
    orchestrator, _ = pg_stack
    session = make_session("CLI-PG-1")
    [row] = orchestrator.gateway.search_customer_transactions(session)
    assert (row["channel"], row["transaction_country"], row["transaction_city"], row["product_currency"]) == ("Web", "USA", "Miami", "COP")
    assert orchestrator.gateway.get_customer_profile(session)["city"] == "Bogotá"
