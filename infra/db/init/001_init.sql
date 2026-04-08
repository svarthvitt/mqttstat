CREATE TABLE IF NOT EXISTS service_healthcheck (
  id SERIAL PRIMARY KEY,
  service_name VARCHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mqtt_metric_records (
  id BIGSERIAL PRIMARY KEY,
  topic TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  numeric_value DOUBLE PRECISION NOT NULL,
  raw_payload TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL
);
