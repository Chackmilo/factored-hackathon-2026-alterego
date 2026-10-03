"""
Operational system of record for the dispute stack (the `ops` schema of docs/SUPABASE_VERCEL.md).

Two backends behind one class: a DuckDB file (default data/ops.duckdb, or ":memory:" for tests) so the
stack works locally and in CI without a Postgres, and Postgres through psycopg when the path is a
postgresql:// URL (Supabase, or a local Postgres). The DDL for Postgres lives in
supabase/migrations/0001_ops.sql; the SQL here sticks to the common subset and is rewritten for
Postgres (`?` placeholders and `ops_x` table names become `%s` and `ops.x`). Every write is followed by
a read-back by the caller (rule 7); the audit log is append-only.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_OPS_PATH = Path("data/ops.duckdb")

DDL = [
    """CREATE TABLE IF NOT EXISTS ops_conversations (
        conversation_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'es',
        state TEXT NOT NULL, clarification_attempts INTEGER NOT NULL DEFAULT 0,
        matched_transaction_id TEXT, candidate_ids TEXT NOT NULL DEFAULT '[]', pending_lock_product_id TEXT,
        created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_messages (
        message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL,
        masked_text TEXT NOT NULL, signals TEXT NOT NULL DEFAULT '{}', created_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_dispute_cases (
        case_id TEXT PRIMARY KEY, conversation_id TEXT, customer_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
        product_id TEXT, case_type TEXT NOT NULL, category TEXT NOT NULL, subcategory TEXT NOT NULL,
        reception_channel TEXT NOT NULL, status TEXT NOT NULL, claimed_amount DOUBLE, currency TEXT, amount_usd DOUBLE,
        cited_clauses TEXT NOT NULL DEFAULT '[]', provisional_credit_candidate BOOLEAN NOT NULL DEFAULT FALSE,
        provisional_credit_amount_usd DOUBLE NOT NULL DEFAULT 0.0, credit_decision TEXT, credit_decided_by TEXT,
        credit_decided_at TIMESTAMP, created_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_card_locks (
        lock_id TEXT PRIMARY KEY, conversation_id TEXT, customer_id TEXT NOT NULL, product_id TEXT,
        reason TEXT NOT NULL, status TEXT NOT NULL, verified BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_handoffs (
        handoff_id TEXT PRIMARY KEY, conversation_id TEXT, customer_id TEXT NOT NULL, escalation_reason TEXT NOT NULL,
        packet TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', resolved_by TEXT, resolved_at TIMESTAMP,
        created_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_team_questions (
        question_id TEXT PRIMARY KEY, topic TEXT NOT NULL, question TEXT NOT NULL, context TEXT NOT NULL DEFAULT '',
        options TEXT NOT NULL DEFAULT '[]', recommendation TEXT, source TEXT, status TEXT NOT NULL DEFAULT 'open',
        answer TEXT, answered_by TEXT, answered_at TIMESTAMP, created_at TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_audit_log (
        audit_id TEXT PRIMARY KEY, conversation_id TEXT, customer_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}', verified BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP NOT NULL)""",
]

JSON_COLUMNS = {"candidate_ids", "signals", "cited_clauses", "packet", "details", "options"}
OPS_TABLES = ("conversations", "messages", "dispute_cases", "card_locks", "handoffs", "audit_log", "team_questions", "llm_usage")
_TABLE_RE = re.compile(r"\bops_(" + "|".join(OPS_TABLES) + r")\b")
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "0001_ops.sql"
DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "team_questions.json"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


class OpsStore:
    """Operational store on DuckDB (file or ':memory:') or Postgres (postgresql:// URL). One connection per call."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path) if path else str(DEFAULT_OPS_PATH)
        self.is_postgres = self.path.startswith(("postgresql://", "postgres://"))
        self._memory_con: duckdb.DuckDBPyConnection | None = None
        if self.is_postgres:
            return  # the schema comes from supabase/migrations/0001_ops.sql (see apply_postgres_migration)
        if self.path == ":memory:":
            self._memory_con = duckdb.connect(":memory:")
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        con = self._con()
        try:
            for stmt in DDL:
                con.execute(stmt)
        finally:
            self._release(con)

    @classmethod
    def apply_postgres_migration(cls, url: str) -> None:
        """Apply supabase/migrations/0001_ops.sql to a Postgres database (idempotent)."""
        import psycopg

        with psycopg.connect(url, autocommit=True) as con:
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                con.execute(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ plumbing
    def _con(self):
        if self.is_postgres:
            import psycopg

            # prepare_threshold=None: Supabase's transaction-mode pooler (Vercel, port 6543) cannot run prepared statements
            return psycopg.connect(self.path, autocommit=True, prepare_threshold=None)
        return self._memory_con if self._memory_con is not None else duckdb.connect(self.path)

    def _release(self, con) -> None:
        if self.is_postgres or self._memory_con is None:
            con.close()

    def _sql(self, sql: str) -> str:
        if not self.is_postgres:
            return sql
        return _TABLE_RE.sub(r"ops.\1", sql).replace("?", "%s")

    def _execute(self, con, sql: str, params: list[Any]):
        if self.is_postgres:
            cur = con.cursor()
            cur.execute(self._sql(sql), params)
            return cur
        return con.execute(sql, params)

    def _run(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        con = self._con()
        try:
            cur = self._execute(con, sql, params or [])
            return cur.fetchall() if cur.description else []
        finally:
            self._release(con)

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        con = self._con()
        try:
            cur = self._execute(con, sql, params or [])
            cols = [d[0] for d in cur.description]
            out = []
            for row in cur.fetchall():
                rec = dict(zip(cols, row))
                for k in JSON_COLUMNS & rec.keys():
                    if isinstance(rec[k], str):
                        rec[k] = json.loads(rec[k])
                for k, v in rec.items():
                    if isinstance(v, datetime):
                        rec[k] = v.isoformat()
                out.append(rec)
            return out
        finally:
            self._release(con)

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    # ------------------------------------------------------------ conversations
    def create_conversation(self, customer_id: str, language: str = "es") -> dict[str, Any]:
        cid = _new_id("CONV")
        now = self._now()
        self._run(
            "INSERT INTO ops_conversations (conversation_id, customer_id, language, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [cid, customer_id, language, "new", now, now],
        )
        return self.get_conversation(cid)

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM ops_conversations WHERE conversation_id = ?", [conversation_id])
        return rows[0] if rows else None

    def update_conversation(self, conversation_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"language", "state", "clarification_attempts", "matched_transaction_id", "candidate_ids", "pending_lock_product_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown conversation fields: {sorted(unknown)}")
        sets, params = [], []
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(json.dumps(v) if k == "candidate_ids" else v)
        sets.append("updated_at = ?")
        params.append(self._now())
        params.append(conversation_id)
        self._run(f"UPDATE ops_conversations SET {', '.join(sets)} WHERE conversation_id = ?", params)
        return self.get_conversation(conversation_id)

    def add_message(self, conversation_id: str, role: str, masked_text: str, signals: dict[str, Any] | None = None) -> str:
        mid = _new_id("MSG")
        self._run(
            "INSERT INTO ops_messages (message_id, conversation_id, role, masked_text, signals, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [mid, conversation_id, role, masked_text, json.dumps(signals or {}, default=str), self._now()],
        )
        return mid

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM ops_messages WHERE conversation_id = ? ORDER BY created_at, message_id", [conversation_id])

    # -------------------------------------------------------------------- cases
    def insert_case(self, *, conversation_id: str | None, customer_id: str, transaction_id: str, product_id: str | None,
                    case_values: dict[str, str], claimed_amount: float | None, currency: str | None, amount_usd: float | None,
                    cited_clauses: list[str], provisional_credit_candidate: bool, provisional_credit_amount_usd: float) -> str:
        case_id = _new_id("CASE")
        self._run(
            """INSERT INTO ops_dispute_cases (case_id, conversation_id, customer_id, transaction_id, product_id, case_type, category,
               subcategory, reception_channel, status, claimed_amount, currency, amount_usd, cited_clauses,
               provisional_credit_candidate, provisional_credit_amount_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [case_id, conversation_id, customer_id, transaction_id, product_id, case_values["case_type"], case_values["category"],
             case_values["subcategory"], case_values["reception_channel"], case_values["status"], claimed_amount, currency,
             amount_usd, json.dumps(cited_clauses), provisional_credit_candidate, provisional_credit_amount_usd, self._now()],
        )
        return case_id

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM ops_dispute_cases WHERE case_id = ?", [case_id])
        return rows[0] if rows else None

    def list_cases(self, customer_id: str | None = None, only_credit_candidates: bool = False) -> list[dict[str, Any]]:
        where, params = [], []
        if customer_id:
            where.append("customer_id = ?")
            params.append(customer_id)
        if only_credit_candidates:
            where.append("provisional_credit_candidate = TRUE")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._rows(f"SELECT * FROM ops_dispute_cases {clause} ORDER BY created_at DESC, case_id", params)

    def decide_credit(self, case_id: str, decision: str, decided_by: str) -> dict[str, Any]:
        if decision not in ("approved", "rejected"):
            raise ValueError("decision must be 'approved' or 'rejected'")
        self._run("UPDATE ops_dispute_cases SET credit_decision = ?, credit_decided_by = ?, credit_decided_at = ? WHERE case_id = ?",
                  [decision, decided_by, self._now(), case_id])
        case = self.get_case(case_id)
        if case is None:
            raise KeyError(case_id)
        return case

    # --------------------------------------------------------------- card locks
    def insert_lock(self, *, conversation_id: str | None, customer_id: str, product_id: str | None, reason: str, status: str) -> str:
        lock_id = _new_id("LOCK")
        now = self._now()
        self._run(
            "INSERT INTO ops_card_locks (lock_id, conversation_id, customer_id, product_id, reason, status, verified, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, FALSE, ?, ?)",
            [lock_id, conversation_id, customer_id, product_id, reason, status, now, now],
        )
        return lock_id

    def update_lock(self, lock_id: str, status: str, verified: bool | None = None) -> dict[str, Any]:
        if verified is None:
            self._run("UPDATE ops_card_locks SET status = ?, updated_at = ? WHERE lock_id = ?", [status, self._now(), lock_id])
        else:
            self._run("UPDATE ops_card_locks SET status = ?, verified = ?, updated_at = ? WHERE lock_id = ?", [status, verified, self._now(), lock_id])
        rows = self._rows("SELECT * FROM ops_card_locks WHERE lock_id = ?", [lock_id])
        return rows[0]

    def list_locks(self, customer_id: str | None = None, conversation_id: str | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if customer_id:
            where.append("customer_id = ?")
            params.append(customer_id)
        if conversation_id:
            where.append("conversation_id = ?")
            params.append(conversation_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._rows(f"SELECT * FROM ops_card_locks {clause} ORDER BY created_at DESC, lock_id", params)

    # ----------------------------------------------------------------- handoffs
    def insert_handoff(self, *, conversation_id: str | None, customer_id: str, escalation_reason: str, packet: dict[str, Any]) -> str:
        handoff_id = _new_id("HO")
        self._run(
            "INSERT INTO ops_handoffs (handoff_id, conversation_id, customer_id, escalation_reason, packet, status, created_at) VALUES (?, ?, ?, ?, ?, 'open', ?)",
            [handoff_id, conversation_id, customer_id, escalation_reason, json.dumps(packet, default=str), self._now()],
        )
        return handoff_id

    def get_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM ops_handoffs WHERE handoff_id = ?", [handoff_id])
        return rows[0] if rows else None

    def list_handoffs(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM ops_handoffs WHERE status = ? ORDER BY created_at DESC, handoff_id", [status])
        return self._rows("SELECT * FROM ops_handoffs ORDER BY created_at DESC, handoff_id")

    def resolve_handoff(self, handoff_id: str, resolved_by: str) -> dict[str, Any]:
        self._run("UPDATE ops_handoffs SET status = 'resolved', resolved_by = ?, resolved_at = ? WHERE handoff_id = ?",
                  [resolved_by, self._now(), handoff_id])
        row = self.get_handoff(handoff_id)
        if row is None:
            raise KeyError(handoff_id)
        return row

    # -------------------------------------------------------------------- audit
    def audit(self, *, conversation_id: str | None, customer_id: str | None, actor: str, action: str,
              details: dict[str, Any] | None = None, verified: bool = False) -> str:
        audit_id = _new_id("AUD")
        self._run(
            "INSERT INTO ops_audit_log (audit_id, conversation_id, customer_id, actor, action, details, verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [audit_id, conversation_id, customer_id, actor, action, json.dumps(details or {}, default=str), verified, self._now()],
        )
        return audit_id

    def list_audit(self, conversation_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if conversation_id:
            return self._rows("SELECT * FROM ops_audit_log WHERE conversation_id = ? ORDER BY created_at, audit_id LIMIT ?", [conversation_id, limit])
        return self._rows("SELECT * FROM ops_audit_log ORDER BY created_at DESC, audit_id LIMIT ?", [limit])

    # -------------------------------------------------------------- case memory
    def case_memory(self, customer_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Facts the system recorded for this customer (team resolution P3), aggregated for DisputePolicyInput."""
        now = now or self._now()
        since_180 = now - timedelta(days=180)
        since_30 = now - timedelta(days=30)
        cases = self._run("SELECT COUNT(*) FROM ops_dispute_cases WHERE customer_id = ? AND created_at >= ?", [customer_id, since_180])[0][0]
        escalations = self._run("SELECT COUNT(*) FROM ops_handoffs WHERE customer_id = ? AND created_at >= ?", [customer_id, since_180])[0][0]
        distress = self._run(
            "SELECT COUNT(*) FROM ops_handoffs WHERE customer_id = ? AND escalation_reason = 'SEVERE_DISTRESS' AND created_at >= ?",
            [customer_id, since_30])[0][0]
        refused = self._run("SELECT COUNT(*) FROM ops_card_locks WHERE customer_id = ? AND status = 'refused'", [customer_id])[0][0]
        return {
            "prior_distress_max_30d": 2.0 if distress else None,
            "prior_escalations_180d": int(escalations),
            "prior_cases_180d": int(cases),
            "prior_lock_refused": bool(refused),
        }

    def recent_disputed_transaction_ids(self, customer_id: str, hours: int = 48, now: datetime | None = None) -> set[str]:
        now = now or self._now()
        rows = self._run("SELECT DISTINCT transaction_id FROM ops_dispute_cases WHERE customer_id = ? AND created_at >= ?",
                         [customer_id, now - timedelta(hours=hours)])
        return {r[0] for r in rows}

    # ------------------------------------------------------------ team questions
    def seed_questions(self, path: str | Path | None = None) -> int:
        """Load the team-generated question fixture; inserts missing ids only, never touches an answered question."""
        data = json.loads(Path(path or DEFAULT_QUESTIONS_PATH).read_text(encoding="utf-8"))
        existing = {q["question_id"]: q for q in self.list_questions()}
        inserted = 0
        for q in data["questions"]:
            stored = existing.get(q["question_id"])
            if stored is None:
                self.insert_question(question_id=q["question_id"], topic=q["topic"], question=q["question"], context=q.get("context", ""),
                                     options=q.get("options", []), recommendation=q.get("recommendation"), source=q.get("source"))
                inserted += 1
                stored = {"status": "open"}
            # an answer recorded in the fixture (for example given in chat) is applied when the store still has the question open
            if q.get("answer") and stored["status"] == "open":
                self.answer_question(q["question_id"], q["answer"], q.get("answered_by", "team (fixture)"))
        return inserted

    def insert_question(self, *, topic: str, question: str, context: str = "", options: list[str] | None = None,
                        recommendation: str | None = None, source: str | None = None, question_id: str | None = None) -> str:
        qid = question_id or _new_id("TQ")
        self._run(
            """INSERT INTO ops_team_questions (question_id, topic, question, context, options, recommendation, source, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            [qid, topic, question, context, json.dumps(options or []), recommendation, source, self._now()],
        )
        return qid

    def get_question(self, question_id: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM ops_team_questions WHERE question_id = ?", [question_id])
        return rows[0] if rows else None

    def list_questions(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self._rows("SELECT * FROM ops_team_questions WHERE status = ? ORDER BY question_id", [status])
        return self._rows("SELECT * FROM ops_team_questions ORDER BY question_id")

    def answer_question(self, question_id: str, answer: str, answered_by: str) -> dict[str, Any]:
        self._run("UPDATE ops_team_questions SET status = 'answered', answer = ?, answered_by = ?, answered_at = ? WHERE question_id = ?",
                  [answer, answered_by, self._now(), question_id])
        row = self.get_question(question_id)
        if row is None:
            raise KeyError(question_id)
        return row
