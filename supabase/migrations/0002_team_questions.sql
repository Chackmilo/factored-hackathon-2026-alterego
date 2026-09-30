-- Open questions for the team, answered in the HITL console. Mirrors ops_team_questions in src/ops/store.py.
CREATE TABLE IF NOT EXISTS ops.team_questions (
    question_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    question TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '',
    options JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendation TEXT,
    source TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered')),
    answer TEXT,
    answered_by TEXT,
    answered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON ops.team_questions TO app_gateway;
