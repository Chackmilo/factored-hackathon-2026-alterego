-- Usage of external model keys, for the daily cap (2 USD per day, team decision TQ-015) and the cost metrics.
CREATE TABLE IF NOT EXISTS ops.llm_usage (
    usage_id TEXT PRIMARY KEY,
    conversation_id TEXT,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS llm_usage_created ON ops.llm_usage (created_at);
GRANT SELECT, INSERT ON ops.llm_usage TO app_gateway;
