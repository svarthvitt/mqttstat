CREATE TABLE IF NOT EXISTS mqtt_runtime_config (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    mqtt_host TEXT NOT NULL,
    mqtt_port INTEGER NOT NULL CHECK (mqtt_port BETWEEN 1 AND 65535),
    mqtt_username TEXT,
    mqtt_password TEXT,
    mqtt_client_id TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
