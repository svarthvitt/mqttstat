# mqttstat

Production-friendly local stack for ingesting MQTT data, storing time-series metrics in PostgreSQL/TimescaleDB, and visualizing results in a React frontend.

## Project structure

```text
.
├── backend/                    # FastAPI API + MQTT ingest service
│   ├── app/
│   ├── config/topic_mappings.yaml
│   ├── migrations/
│   └── Dockerfile
├── frontend/                   # React (Vite) app served by Nginx in production image
│   ├── src/
│   ├── nginx.conf
│   └── Dockerfile
├── infra/
│   ├── db/init/                # One-time DB init scripts
│   ├── migrations/
│   └── seeds/                  # Optional sample seed data
├── docker-compose.yml
└── .env.example
```

## Services in `docker-compose.yml`

- `postgres-timescaledb`: TimescaleDB (Postgres 16), persistent storage via named volume `mqttstat_pg_data`.
- `backend`: FastAPI + MQTT consumer service.
- `frontend`: Nginx-served static frontend bundle.
- `migrate` (optional): runs backend SQL migrations and exits.
- `seed` (optional): loads sample time-series data and exits.

All long-running services include healthchecks, and startup dependencies use `depends_on` with health conditions.

## Environment configuration (`.env`)

Copy the template and customize:

```bash
cp .env.example .env
```

### Required/important fields

#### Database
- `POSTGRES_DB`: database name.
- `POSTGRES_USER`: database user.
- `POSTGRES_PASSWORD`: database password.
- `POSTGRES_PORT`: host port mapped to container `5432`.
- `DATABASE_URL`: DSN used by backend and migration job (should point at `postgres-timescaledb` inside Compose).

#### App ports
- `BACKEND_PORT`: host port mapped to backend container `8000`.
- `FRONTEND_PORT`: host port mapped to frontend container `80`.

#### Frontend API endpoint
- `VITE_API_BASE_URL`: base URL baked into frontend build for API calls (for local Docker, `http://localhost:8000`).

#### MQTT credentials and connectivity
- `MQTT_BROKER_HOST`: MQTT broker host or service name reachable from backend.
- `MQTT_BROKER_PORT`: MQTT broker port.
- `MQTT_BROKER_USER`: MQTT username (leave empty for anonymous broker).
- `MQTT_BROKER_PASS`: MQTT password.
- `MQTT_CLIENT_ID`: MQTT client identifier used by backend.
- `MQTT_TOPIC_MAP_PATH`: path to YAML topic mapping file loaded at backend startup.

## Startup commands

### 1) Build and run core services

```bash
docker compose up --build -d postgres-timescaledb backend frontend
```

### 2) Check health/status

```bash
docker compose ps
```

### 3) Tail logs

```bash
docker compose logs -f backend frontend postgres-timescaledb
```

### 4) Stop stack

```bash
docker compose down
```

> To also remove persisted DB data: `docker compose down -v`

## Optional migration/init service

The backend already runs migrations on startup, but you can run migrations explicitly:

```bash
docker compose --profile ops run --rm migrate
```

Use this for controlled pre-flight migration runs in CI/CD or before backend deploys.

## Sample seed data

Seed file: `infra/seeds/001_sample_data.sql`

It inserts example topics and recent measurements for:
- `sensors/lab/environment` (`temperature_c`, `humidity_pct`)
- `sensors/lab/power_watts` (`power_watts`)

### Load sample data

```bash
docker compose --profile ops run --rm seed
```

### Verify sample records loaded

```bash
docker compose exec postgres-timescaledb \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM measurements;"
```

## Adding new topic mappings later

Edit `backend/config/topic_mappings.yaml` and add a new topic entry. Example:

```yaml
topics:
  - topic: sensors/warehouse/environment
    payload_type: json
    qos: 1
    fields:
      - metric_key: temperature_c
        field: temperature.c
      - metric_key: humidity_pct
        field: humidity
```

For raw numeric payloads:

```yaml
  - topic: sensors/warehouse/power_watts
    payload_type: raw_numeric
    qos: 0
    metric_key: power_watts
```

Then restart backend so it reloads mapping config:

```bash
docker compose restart backend
```

## Service URLs

- Frontend: `http://localhost:${FRONTEND_PORT}` (default `http://localhost:5173`)
- Backend API: `http://localhost:${BACKEND_PORT}` (default `http://localhost:8000`)
- Backend health: `http://localhost:${BACKEND_PORT}/health`
- Frontend health: `http://localhost:${FRONTEND_PORT}/healthz`
- PostgreSQL: `localhost:${POSTGRES_PORT}`
