"""Runtime connections never prepare statements.

On Vercel the API reaches Supabase through the shared pooler in transaction mode (port 6543, docs/SUPABASE_VERCEL.md
section 6.7), which hands each transaction to any backend and does not support prepared statements. psycopg prepares a
query once it has run prepare_threshold times (5 by default) on one connection, so a loop that repeats a statement on
one connection would fail there with "prepared statement ... does not exist". Runs when TEST_DATABASE_URL is set.
"""
import os

import pytest

from src.ops.store import OpsStore
from src.tools.gateway_postgres import PostgresBankingGateway

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
REPEATS = 10  # well past psycopg's default prepare_threshold of 5


def _prepared_after_repeats(con) -> int:
    for _ in range(REPEATS):
        con.execute("SELECT %s::int", (1,)).fetchone()
    return con.execute("SELECT count(*) FROM pg_prepared_statements").fetchone()[0]


def test_the_ops_store_connection_prepares_no_statement():
    store = OpsStore(os.environ["TEST_DATABASE_URL"])
    con = store._con()
    try:
        assert _prepared_after_repeats(con) == 0
    finally:
        store._release(con)


def test_the_gateway_connection_prepares_no_statement():
    with PostgresBankingGateway(os.environ["TEST_DATABASE_URL"])._con() as con:
        assert _prepared_after_repeats(con) == 0
