"""
Round trip of the operational store on both backends. The Postgres case runs only when TEST_DATABASE_URL points
to an empty local database (for example postgresql://localhost/alterego_ops_test); it applies the Supabase
migration first, so the DDL, the CHECK constraints and the append-only trigger are exercised for real.
"""
import os

import pytest

from src.ops.store import OpsStore


@pytest.fixture(params=["duckdb", "postgres"])
def store(request):
    if request.param == "duckdb":
        return OpsStore(":memory:")
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; Postgres round trip skipped")
    OpsStore.apply_postgres_migration(url)
    s = OpsStore(url)
    for table in ("audit_log", "team_questions", "handoffs", "card_locks", "dispute_cases", "messages", "conversations"):
        if table == "audit_log":
            continue  # append-only: the trigger rejects DELETE; test rows carry unique ids
        s._run(f"DELETE FROM ops_{table}")
    return s


CASE_VALUES = {"case_type": "Claim", "category": "Transactions", "subcategory": "Cargo no reconocido",
               "reception_channel": "App", "status": "Open"}


def test_conversation_case_handoff_lock_and_audit_round_trip(store):
    conv = store.create_conversation("CLI-STORE-1", language="pt")
    cid = conv["conversation_id"]
    assert conv["state"] == "new" and conv["language"] == "pt" and conv["candidate_ids"] == []
    store.update_conversation(cid, state="awaiting_clarification", candidate_ids=["TRX-1", "TRX-2"], clarification_attempts=1)
    assert store.get_conversation(cid)["candidate_ids"] == ["TRX-1", "TRX-2"]
    store.add_message(cid, "customer", "mensagem mascarada", {"intent": "cargo_no_reconocido"})
    assert store.list_messages(cid)[0]["signals"]["intent"] == "cargo_no_reconocido"

    case_id = store.insert_case(conversation_id=cid, customer_id="CLI-STORE-1", transaction_id="TRX-1", product_id="PRD-1",
                                case_values=CASE_VALUES, claimed_amount=80.0, currency="USD", amount_usd=80.0,
                                cited_clauses=["POL-DISP-TYPE", "POL-WIN-60", "POL-AUT-INTAKE", "POL-AUT-150"],
                                provisional_credit_candidate=True, provisional_credit_amount_usd=80.0)
    case = store.get_case(case_id)
    assert case["status"] == "Open" and case["cited_clauses"][-1] == "POL-AUT-150" and case["provisional_credit_candidate"] is True
    assert [c["case_id"] for c in store.list_cases(customer_id="CLI-STORE-1", only_credit_candidates=True)] == [case_id]
    assert store.decide_credit(case_id, "approved", "AGENT-1")["credit_decision"] == "approved"

    lock_id = store.insert_lock(conversation_id=cid, customer_id="CLI-STORE-1", product_id="PRD-1", reason="STOLEN_CARD_CLAIM", status="offered")
    assert store.update_lock(lock_id, "locked", verified=True)["verified"] is True

    handoff_id = store.insert_handoff(conversation_id=cid, customer_id="CLI-STORE-1", escalation_reason="SEVERE_DISTRESS",
                                      packet={"verified_facts": ["fact"], "applicable_policy_clauses": ["POL-ESC-DISTRESS"]})
    assert store.get_handoff(handoff_id)["packet"]["applicable_policy_clauses"] == ["POL-ESC-DISTRESS"]
    assert store.resolve_handoff(handoff_id, "AGENT-1")["status"] == "resolved"

    store.audit(conversation_id=cid, customer_id="CLI-STORE-1", actor="system", action="OPEN_DISPUTE", details={"case_id": case_id}, verified=True)
    assert any(a["action"] == "OPEN_DISPUTE" and a["verified"] for a in store.list_audit(conversation_id=cid))

    memory = store.case_memory("CLI-STORE-1")
    assert memory == {"prior_distress_max_30d": 2.0, "prior_escalations_180d": 1, "prior_cases_180d": 1, "prior_lock_refused": False}
    assert store.recent_disputed_transaction_ids("CLI-STORE-1") == {"TRX-1"}


def test_postgres_audit_log_is_append_only():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    OpsStore.apply_postgres_migration(url)
    store = OpsStore(url)
    audit_id = store.audit(conversation_id=None, customer_id="CLI-STORE-2", actor="system", action="TEST")
    with psycopg.connect(url, autocommit=True) as con, pytest.raises(psycopg.errors.RaiseException):
        con.execute("UPDATE ops.audit_log SET action = 'CHANGED' WHERE audit_id = %s", [audit_id])


def test_team_questions_seed_and_answer(store):
    inserted = store.seed_questions()
    assert inserted >= 17
    assert store.seed_questions() == 0  # idempotent
    q = store.get_question("TQ-002")
    assert q["status"] == "open" and q["options"][0] == "Fail the load (recommended)"
    answered = store.answer_question("TQ-002", "Fail the load", "AGENT-1")
    assert answered["status"] == "answered" and answered["answered_by"] == "AGENT-1"
    assert store.seed_questions() == 0 and store.get_question("TQ-002")["answer"] == "Fail the load"
    assert "TQ-002" not in {q["question_id"] for q in store.list_questions(status="open")}
    # answers recorded in the fixture (given in chat on 27-Sep) are applied on seed and never overwritten
    assert store.get_question("TQ-001")["status"] == "answered" and store.get_question("TQ-001")["answered_by"].startswith("team")
    assert store.get_question("TQ-019")["status"] == "open"
    new_id = store.insert_question(topic="Loop", question="A new question?", options=["a", "b"])
    assert store.get_question(new_id)["status"] == "open"


def test_postgres_functions_the_advisor_flags_have_a_fixed_search_path():
    """Supabase's security advisor flags a mutable search_path on ops.reject_audit_change and ops.business_today (migration 0005)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    import psycopg

    OpsStore.apply_postgres_migration(url)
    with psycopg.connect(url, autocommit=True) as con:
        rows = dict(con.execute("""SELECT p.proname, p.proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                                   WHERE n.nspname = 'ops' AND p.proname IN ('reject_audit_change', 'business_today')""").fetchall())
    assert set(rows) == {"reject_audit_change", "business_today"}
    assert all(config is not None and any(c.startswith("search_path=") for c in config) for config in rows.values())
