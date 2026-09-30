-- ops schema for Supabase Postgres (docs/SUPABASE_VERCEL.md section 4). Mirrors src/ops/store.py.
-- Apply with the Supabase CLI or psql as the project owner; the API connects as app_gateway.
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.conversations (
    conversation_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'es' CHECK (language IN ('es', 'pt')),
    state TEXT NOT NULL,
    clarification_attempts INTEGER NOT NULL DEFAULT 0,
    matched_transaction_id TEXT,
    candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_lock_product_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES ops.conversations (conversation_id),
    role TEXT NOT NULL CHECK (role IN ('customer', 'assistant')),
    masked_text TEXT NOT NULL,
    signals JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.dispute_cases (
    case_id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES ops.conversations (conversation_id),
    customer_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    product_id TEXT,
    case_type TEXT NOT NULL CHECK (case_type IN ('Claim')),
    category TEXT NOT NULL CHECK (category IN ('Transactions')),
    subcategory TEXT NOT NULL CHECK (subcategory IN ('Cargo no reconocido', 'Cobro indebido')),
    reception_channel TEXT NOT NULL CHECK (reception_channel IN ('App')),
    status TEXT NOT NULL CHECK (status IN ('Open', 'In Progress', 'Resolved', 'Closed')),
    claimed_amount DOUBLE PRECISION,
    currency TEXT,
    amount_usd DOUBLE PRECISION,
    cited_clauses JSONB NOT NULL DEFAULT '[]'::jsonb,
    provisional_credit_candidate BOOLEAN NOT NULL DEFAULT FALSE,
    provisional_credit_amount_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    credit_decision TEXT CHECK (credit_decision IN ('approved', 'rejected')),
    credit_decided_by TEXT,
    credit_decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.card_locks (
    lock_id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES ops.conversations (conversation_id),
    customer_id TEXT NOT NULL,
    product_id TEXT,
    reason TEXT NOT NULL CHECK (reason IN ('STOLEN_CARD_CLAIM', 'MULTI_CHARGE_FRAUD')),
    status TEXT NOT NULL CHECK (status IN ('offered', 'refused', 'locked', 'unlocked')),
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.handoffs (
    handoff_id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES ops.conversations (conversation_id),
    customer_id TEXT NOT NULL,
    escalation_reason TEXT NOT NULL,
    packet JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.audit_log (
    audit_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    customer_id TEXT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only audit log: the gateway role may only INSERT and SELECT, and a trigger rejects changes.
CREATE OR REPLACE FUNCTION ops.reject_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ops.audit_log is append-only';
END;
$$;
DROP TRIGGER IF EXISTS audit_log_append_only ON ops.audit_log;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON ops.audit_log
    FOR EACH ROW EXECUTE FUNCTION ops.reject_audit_change();

-- Least-privilege role for the API (SEC-07): no BYPASSRLS, no DELETE, INSERT-only on the audit log.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_gateway') THEN
        CREATE ROLE app_gateway NOLOGIN NOBYPASSRLS;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA ops TO app_gateway;
GRANT SELECT, INSERT, UPDATE ON ops.conversations, ops.messages, ops.dispute_cases, ops.card_locks, ops.handoffs TO app_gateway;
GRANT SELECT, INSERT ON ops.audit_log TO app_gateway;
