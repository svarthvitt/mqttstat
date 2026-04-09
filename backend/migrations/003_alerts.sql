CREATE TABLE IF NOT EXISTS alert_rules (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    metric TEXT NOT NULL,
    condition TEXT NOT NULL, -- 'gt', 'lt', 'eq', 'gte', 'lte'
    threshold DOUBLE PRECISION NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_history (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    observed_value DOUBLE PRECISION NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alert_history_rule_ts ON alert_history (rule_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_alert_rules_topic_metric ON alert_rules (topic, metric) WHERE enabled = TRUE;
