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

## Configure MQTT from UI

You can manage broker connectivity at runtime in the frontend:

1. Open the frontend (`http://localhost:${FRONTEND_PORT}`).
2. Click **MQTT config** in the top navigation (route `#/config`).
3. Set broker host, port, username/password, and client ID.
4. Click **Save config**.

### Runtime behavior after save

- Saving writes the values into backend persistence (`mqtt_runtime_config` table).
- The backend immediately reloads and reconnects the MQTT ingest client using the new values (no container restart required).
- If the new connection fails, the API returns an error and the UI shows that failure.

### Security caveats

- The MQTT password is persisted in the database as plaintext in `mqtt_runtime_config.mqtt_password`.
- The API never returns the password value directly; `GET /api/config/mqtt` exposes only a `has_password` boolean.
- Restrict network/database access and use infrastructure-level controls (private network, encrypted disk, backups policy, secret rotation).

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

## Production-like smoke script

Use `scripts/prod-smoke.sh` to validate the running stack the same way the UI does.

### What it does

1. Starts `postgres-timescaledb`, `backend`, and `frontend` with:

   ```bash
   docker compose up -d --build postgres-timescaledb backend frontend
   ```
2. Waits for:
   - `http://localhost:${FRONTEND_PORT}/healthz`
   - `http://localhost:${BACKEND_PORT}/health`
3. Runs dependency checks:
   - `GET /api/config/mqtt`
   - `GET /api/dashboard?from=<iso>&to=<iso>`
   - `GET /api/topics`
   - optional `GET /api/timeseries?...` when at least one `topic:metric` id exists
4. If any check fails (non-2xx or JSON parse/shape failure), it prints request details and writes diagnostics:
   - `docker compose logs --no-color backend frontend postgres-timescaledb`
   - `docker compose ps`
   - failure summary
5. Exits non-zero on failures for CI usage.

### Run it

```bash
./scripts/prod-smoke.sh
```

### Expected output

Pass example:

```text
Starting production-like services
Waiting for frontend health at http://localhost:5173/healthz
OK: frontend is healthy
Waiting for backend health at http://localhost:8000/health
OK: backend is healthy
OK: GET /api/config/mqtt
OK: GET /api/dashboard
OK: GET /api/topics
SKIP: GET /api/timeseries (no topics discovered)
Smoke test passed.
```

Fail example:

```text
FAIL: GET /api/topics returned non-2xx
  URL: http://localhost:8000/api/topics
  Status: 500
  Body snippet: {"detail":"..."}
Collecting docker compose diagnostics in /workspace/mqttstat/artifacts/smoke-20260411T120000Z
Smoke test failed with 1 check(s) failing.
Artifacts: /workspace/mqttstat/artifacts/smoke-20260411T120000Z
```

Artifacts are written under `artifacts/smoke-<timestamp>/`.

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

## Publish images to Docker registry

Use this flow when you want pre-built images for deployment hosts (instead of building directly on each host).

### Prerequisites

- Docker Buildx is available:

  ```bash
  docker buildx version
  ```

- You have a registry account and created repositories for both images:
  - `mqttstat-backend`
  - `mqttstat-frontend`

Set variables used in the examples:

```bash
export REGISTRY_USER="your-registry-user"
export VERSION="1.2.0"
```

### Recommended image naming

- Backend: `REGISTRY_USER/mqttstat-backend:<version>`
- Frontend: `REGISTRY_USER/mqttstat-frontend:<version>`

Examples:
- `${REGISTRY_USER}/mqttstat-backend:${VERSION}`
- `${REGISTRY_USER}/mqttstat-frontend:${VERSION}`

### Authenticate to registry

#### Docker Hub

```bash
docker login
```

#### GHCR (`ghcr.io`) variant

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
```

For GHCR image names, prefix with `ghcr.io/`, for example:
- `ghcr.io/${GHCR_USER}/mqttstat-backend:${VERSION}`
- `ghcr.io/${GHCR_USER}/mqttstat-frontend:${VERSION}`

### Build and push from repo root

Run these commands from the repository root (`/workspace/mqttstat`).

#### Backend (`backend/Dockerfile`)

Single-arch (example: `linux/amd64`):

```bash
docker buildx build \
  --platform linux/amd64 \
  -f backend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-backend:${VERSION}" \
  --push \
  .
```

Optional multi-arch (`linux/amd64,linux/arm64`):

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f backend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-backend:${VERSION}" \
  --push \
  .
```

#### Frontend (`frontend/Dockerfile`)

Single-arch (example: `linux/amd64`):

```bash
docker buildx build \
  --platform linux/amd64 \
  -f frontend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-frontend:${VERSION}" \
  --push \
  .
```

Optional multi-arch (`linux/amd64,linux/arm64`):

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f frontend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-frontend:${VERSION}" \
  --push \
  .
```

### Versioning and tagging policy

Use semantic versions for immutable releases (for example: `1.2.0`) and optionally maintain a moving `latest` tag.

Example tag and push flow:

```bash
# Backend
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f backend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-backend:${VERSION}" \
  -t "${REGISTRY_USER}/mqttstat-backend:latest" \
  --push \
  .

# Frontend
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f frontend/Dockerfile \
  -t "${REGISTRY_USER}/mqttstat-frontend:${VERSION}" \
  -t "${REGISTRY_USER}/mqttstat-frontend:latest" \
  --push \
  .
```

### Verify published images

```bash
docker pull "${REGISTRY_USER}/mqttstat-backend:${VERSION}"
docker pull "${REGISTRY_USER}/mqttstat-frontend:${VERSION}"
```

(And optionally verify `:latest` similarly.)

### Compose deployment note (`image:` instead of `build:`)

On deployment hosts, prefer pulling published images rather than building locally. In `docker-compose.yml`, replace `build:` with `image:` for backend/frontend services.

Example:

```yaml
services:
  backend:
    image: ${BACKEND_IMAGE:-your-registry-user/mqttstat-backend:1.2.0}
    # build: ./backend

  frontend:
    image: ${FRONTEND_IMAGE:-your-registry-user/mqttstat-frontend:1.2.0}
    # build: ./frontend
```

You can then provide `BACKEND_IMAGE` and `FRONTEND_IMAGE` via `.env` for each environment.

### Release checklist

Before announcing a release, quickly confirm:

- Tag chosen and consistent (semantic version + optional `latest`).
- Images pushed successfully for backend and frontend.
- `docker pull` verification succeeded for published tags.
- Deployment Compose/env updated to target the new image tags.
- Deployment completed and services are healthy.
