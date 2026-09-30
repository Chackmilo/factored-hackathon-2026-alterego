-- bank: read-only serving copy of the lakehouse gold layer (docs/SUPABASE_VERCEL.md section 4).
-- Minimized on purpose (rule 10): no documents, contacts, card numbers, balances, is_fraud or fraud_score.
-- Reloaded by src/data/publish_serving.py in one transaction; never written by the app.
CREATE SCHEMA IF NOT EXISTS bank;

CREATE TABLE IF NOT EXISTS bank.customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT,
    country TEXT NOT NULL,
    city TEXT,
    segment TEXT NOT NULL CHECK (segment IN ('Premium', 'Plus', 'Basic', 'Student')),
    registration_date TIMESTAMP,
    customer_status TEXT
);

CREATE TABLE IF NOT EXISTS bank.products (
    product_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES bank.customers (customer_id),
    product_type TEXT NOT NULL,
    product_status TEXT NOT NULL,
    currency TEXT,
    opening_date DATE,
    expiration_date DATE,
    last4 TEXT
);

CREATE TABLE IF NOT EXISTS bank.transactions (
    transaction_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES bank.customers (customer_id),
    product_id TEXT REFERENCES bank.products (product_id),
    transaction_date TIMESTAMP NOT NULL,   -- as in the CSV, no time zone (section 4.3 rule 2)
    process_date DATE NOT NULL,            -- the bank's processing day, never recomputed here
    transaction_type TEXT NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    currency TEXT NOT NULL,
    amount_usd DOUBLE PRECISION NOT NULL,
    amount_usd_source TEXT NOT NULL CHECK (amount_usd_source IN ('native', 'same_currency', 'daily_rate_fill')),
    channel TEXT,
    merchant_name TEXT,
    merchant_category TEXT,
    transaction_country TEXT,
    transaction_city TEXT,
    transaction_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bank.complaints (
    complaint_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES bank.customers (customer_id),
    creation_date TIMESTAMP,
    process_date DATE,
    case_type TEXT,
    category TEXT,
    subcategory TEXT,
    status TEXT,
    claimed_amount DOUBLE PRECISION,
    currency TEXT,
    is_repeat_complainer BOOLEAN
);

CREATE TABLE IF NOT EXISTS bank.exchange_rates (
    rate_date DATE NOT NULL,
    source_currency TEXT NOT NULL,
    target_currency TEXT NOT NULL,
    exchange_rate DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (rate_date, source_currency, target_currency)
);

CREATE INDEX IF NOT EXISTS transactions_customer_process_date ON bank.transactions (customer_id, process_date DESC);
CREATE INDEX IF NOT EXISTS products_customer ON bank.products (customer_id);
CREATE INDEX IF NOT EXISTS complaints_customer_creation ON bank.complaints (customer_id, creation_date);

-- "Today" is the dataset end date; the Python constant (DisputePolicyInput.current_date) must match it (section 4.6).
CREATE OR REPLACE FUNCTION ops.business_today() RETURNS DATE LANGUAGE sql IMMUTABLE AS $$ SELECT DATE '2026-06-17' $$;

-- Effective product status: bank.products replaced by the latest verified lock in ops.card_locks (section 4.5).
CREATE OR REPLACE VIEW ops.v_product_status AS
SELECT p.product_id, p.customer_id, p.product_type,
       CASE WHEN l.status = 'locked' THEN 'Blocked' ELSE p.product_status END AS product_status,
       l.lock_id AS active_lock_id
FROM bank.products p
LEFT JOIN LATERAL (
    SELECT c.lock_id, c.status FROM ops.card_locks c
    WHERE c.product_id = p.product_id AND c.verified ORDER BY c.updated_at DESC LIMIT 1
) l ON TRUE;

-- Live policy facts: account age from the registration date, complaints from bank plus the cases the system opened.
CREATE OR REPLACE VIEW ops.v_customer_policy_facts AS
SELECT c.customer_id, c.full_name, c.country, c.segment,
       (ops.business_today() - c.registration_date::date) AS account_age_days,
       ((ops.business_today() - c.registration_date::date) > 180) AS is_account_mature,
       (SELECT COUNT(*) FROM bank.complaints k WHERE k.customer_id = c.customer_id
            AND k.process_date >= ops.business_today() - 90 AND k.process_date <= ops.business_today())
       + (SELECT COUNT(*) FROM ops.dispute_cases d WHERE d.customer_id = c.customer_id
            AND d.created_at::date >= ops.business_today() - 90) AS complaints_last_90d,
       (SELECT COUNT(*) FROM ops.v_product_status s WHERE s.customer_id = c.customer_id AND s.product_status = 'Active') AS active_products
FROM bank.customers c;

GRANT USAGE ON SCHEMA bank TO app_gateway;
GRANT SELECT ON ALL TABLES IN SCHEMA bank TO app_gateway;
GRANT SELECT ON ops.v_product_status, ops.v_customer_policy_facts TO app_gateway;
