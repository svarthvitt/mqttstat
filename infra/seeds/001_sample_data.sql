-- Sample data for local development and demos.
-- Idempotent inserts so this file can be run multiple times safely.

INSERT INTO topics (name, payload_type)
VALUES
  ('sensors/lab/environment', 'json'),
  ('sensors/lab/power_watts', 'raw_numeric')
ON CONFLICT (name) DO NOTHING;

WITH env_topic AS (
  SELECT id FROM topics WHERE name = 'sensors/lab/environment'
),
power_topic AS (
  SELECT id FROM topics WHERE name = 'sensors/lab/power_watts'
),
seed_points AS (
  SELECT
    now() - (n * INTERVAL '5 minutes') AS ts,
    round((21.5 + (n % 6) * 0.4)::numeric, 2)::double precision AS temperature_c,
    round((44 + (n % 5) * 1.3)::numeric, 2)::double precision AS humidity_pct,
    round((310 + (n % 8) * 6.7)::numeric, 2)::double precision AS power_watts
  FROM generate_series(0, 47) AS g(n)
)
INSERT INTO measurements (topic_id, metric, value, ts, payload_json, raw_payload)
SELECT
  et.id,
  'temperature_c',
  sp.temperature_c,
  sp.ts,
  jsonb_build_object('temperature', jsonb_build_object('c', sp.temperature_c), 'humidity', sp.humidity_pct),
  format('{"temperature":{"c":%s},"humidity":%s}', sp.temperature_c, sp.humidity_pct)
FROM seed_points sp
CROSS JOIN env_topic et
WHERE NOT EXISTS (
  SELECT 1 FROM measurements m WHERE m.topic_id = et.id AND m.metric = 'temperature_c' AND m.ts = sp.ts
);

WITH env_topic AS (
  SELECT id FROM topics WHERE name = 'sensors/lab/environment'
),
seed_points AS (
  SELECT
    now() - (n * INTERVAL '5 minutes') AS ts,
    round((44 + (n % 5) * 1.3)::numeric, 2)::double precision AS humidity_pct
  FROM generate_series(0, 47) AS g(n)
)
INSERT INTO measurements (topic_id, metric, value, ts, payload_json, raw_payload)
SELECT
  et.id,
  'humidity_pct',
  sp.humidity_pct,
  sp.ts,
  jsonb_build_object('humidity', sp.humidity_pct),
  format('{"humidity":%s}', sp.humidity_pct)
FROM seed_points sp
CROSS JOIN env_topic et
WHERE NOT EXISTS (
  SELECT 1 FROM measurements m WHERE m.topic_id = et.id AND m.metric = 'humidity_pct' AND m.ts = sp.ts
);

WITH power_topic AS (
  SELECT id FROM topics WHERE name = 'sensors/lab/power_watts'
),
seed_points AS (
  SELECT
    now() - (n * INTERVAL '5 minutes') AS ts,
    round((310 + (n % 8) * 6.7)::numeric, 2)::double precision AS power_watts
  FROM generate_series(0, 47) AS g(n)
)
INSERT INTO measurements (topic_id, metric, value, ts, payload_json, raw_payload)
SELECT
  pt.id,
  'power_watts',
  sp.power_watts,
  sp.ts,
  jsonb_build_object('power_watts', sp.power_watts),
  sp.power_watts::text
FROM seed_points sp
CROSS JOIN power_topic pt
WHERE NOT EXISTS (
  SELECT 1 FROM measurements m WHERE m.topic_id = pt.id AND m.metric = 'power_watts' AND m.ts = sp.ts
);
