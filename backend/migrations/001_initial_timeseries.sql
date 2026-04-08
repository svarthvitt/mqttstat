CREATE TABLE IF NOT EXISTS topics (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    payload_type TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS measurements (
    id BIGSERIAL,
    topic_id BIGINT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    payload_json JSONB,
    raw_payload TEXT,
    PRIMARY KEY (id, ts)
);

CREATE INDEX IF NOT EXISTS idx_measurements_topic_ts
    ON measurements (topic_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_measurements_topic_metric_ts
    ON measurements (topic_id, metric, ts DESC);

CREATE INDEX IF NOT EXISTS idx_measurements_metric_ts
    ON measurements (metric, ts DESC);

DO $$
BEGIN
    IF to_regclass('public.mqtt_metric_records') IS NOT NULL THEN
        INSERT INTO topics (name)
        SELECT DISTINCT topic
        FROM mqtt_metric_records
        ON CONFLICT (name) DO NOTHING;

        INSERT INTO measurements (topic_id, metric, value, ts, raw_payload)
        SELECT t.id, r.metric_key, r.numeric_value, r.observed_at, r.raw_payload
        FROM mqtt_metric_records r
        JOIN topics t ON t.name = r.topic;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
    END IF;
END
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'timescaledb'
    ) THEN
        PERFORM create_hypertable('measurements', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

        ALTER TABLE measurements
            SET (
                timescaledb.compress,
                timescaledb.compress_segmentby = 'topic_id,metric',
                timescaledb.compress_orderby = 'ts DESC'
            );

        PERFORM add_compression_policy('measurements', INTERVAL '7 days', if_not_exists => TRUE);
        PERFORM add_retention_policy('measurements', INTERVAL '90 days', if_not_exists => TRUE);
    END IF;
END
$$;
