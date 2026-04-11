#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_BASE="http://localhost:${FRONTEND_PORT}"
BACKEND_BASE="http://localhost:${BACKEND_PORT}"

COMPOSE_SERVICES=(postgres-timescaledb backend frontend)
FAILURES=0
ARTIFACT_DIR=""

ensure_artifacts() {
  if [[ -n "$ARTIFACT_DIR" ]]; then
    return
  fi

  local ts
  ts="$(date -u +"%Y%m%dT%H%M%SZ")"
  ARTIFACT_DIR="${ROOT_DIR}/artifacts/smoke-${ts}"
  mkdir -p "$ARTIFACT_DIR"

  echo "Collecting docker compose diagnostics in ${ARTIFACT_DIR}"
  docker compose logs --no-color "${COMPOSE_SERVICES[@]}" >"${ARTIFACT_DIR}/docker-compose-logs.txt" 2>&1 || true
  docker compose ps >"${ARTIFACT_DIR}/docker-compose-ps.txt" 2>&1 || true
}

record_failure() {
  local message="$1"
  local url="$2"
  local status="$3"
  local body="$4"

  FAILURES=$((FAILURES + 1))
  echo "FAIL: ${message}"
  echo "  URL: ${url}"
  echo "  Status: ${status}"
  echo "  Body snippet: ${body:0:300}"

  ensure_artifacts
  {
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] ${message}"
    echo "URL: ${url}"
    echo "Status: ${status}"
    echo "Body snippet: ${body:0:500}"
    echo ""
  } >>"${ARTIFACT_DIR}/failures.txt"
}

wait_for_health() {
  local name="$1"
  local url="$2"
  local attempts=60

  echo "Waiting for ${name} health at ${url}"
  for ((i = 1; i <= attempts; i++)); do
    local status
    status="$(curl -sS -o /tmp/smoke_health_body_$$.txt -w "%{http_code}" "$url" || true)"
    if [[ "$status" =~ ^2[0-9]{2}$ ]]; then
      echo "OK: ${name} is healthy"
      rm -f /tmp/smoke_health_body_$$.txt
      return 0
    fi
    sleep 2
  done

  local body=""
  if [[ -f /tmp/smoke_health_body_$$.txt ]]; then
    body="$(cat /tmp/smoke_health_body_$$.txt)"
    rm -f /tmp/smoke_health_body_$$.txt
  fi
  record_failure "Health check failed for ${name}" "$url" "$status" "$body"
  return 1
}

request_json() {
  local label="$1"
  local url="$2"
  local validator="$3"
  local body_file
  body_file="$(mktemp)"

  local status
  status="$(curl -sS -o "$body_file" -w "%{http_code}" "$url" || true)"
  local body
  body="$(cat "$body_file")"
  rm -f "$body_file"

  if ! [[ "$status" =~ ^2[0-9]{2}$ ]]; then
    record_failure "${label} returned non-2xx" "$url" "$status" "$body"
    return 1
  fi

  if ! python3 - <<'PY' "$body" "$validator"
import json
import sys

payload = json.loads(sys.argv[1])
validator = sys.argv[2]

if validator == "mqtt":
    required = ["mqtt_host", "mqtt_port", "mqtt_client_id", "has_password"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise SystemExit(f"missing keys: {missing}")
elif validator == "dashboard":
    if "cards" not in payload or "kpis" not in payload:
        raise SystemExit("missing dashboard keys")
elif validator == "topics":
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise SystemExit("topics is not a list")
elif validator == "timeseries":
    series = payload.get("series")
    if not isinstance(series, list):
        raise SystemExit("series is not a list")
else:
    raise SystemExit(f"unknown validator: {validator}")
PY
  then
    record_failure "${label} JSON parse/validation failed" "$url" "$status" "$body"
    return 1
  fi

  echo "OK: ${label}"
  if [[ "$validator" == "topics" ]]; then
    TOPICS_JSON="$body"
  fi
  return 0
}

TOPICS_JSON='{"topics":[]}'

echo "Starting production-like services"
docker compose up -d --build "${COMPOSE_SERVICES[@]}"

wait_for_health "frontend" "${FRONTEND_BASE}/healthz" || true
wait_for_health "backend" "${BACKEND_BASE}/health" || true

read -r FROM_ISO TO_ISO < <(python3 - <<'PY'
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc).replace(microsecond=0)
start = now - timedelta(hours=1)
print(start.isoformat().replace("+00:00", "Z"), now.isoformat().replace("+00:00", "Z"))
PY
)

request_json "GET /api/config/mqtt" "${BACKEND_BASE}/api/config/mqtt" "mqtt" || true
request_json "GET /api/dashboard" "${BACKEND_BASE}/api/dashboard?from=${FROM_ISO}&to=${TO_ISO}" "dashboard" || true
request_json "GET /api/topics" "${BACKEND_BASE}/api/topics" "topics" || true

SERIES_ID="$(python3 - <<'PY' "$TOPICS_JSON"
import json
import sys

payload = json.loads(sys.argv[1])
topics = payload.get("topics") or []
print(topics[0]["id"] if topics else "")
PY
)"

if [[ -n "$SERIES_ID" ]]; then
  SERIES_ENCODED="$(python3 - <<'PY' "$SERIES_ID"
import sys
from urllib.parse import quote
print(quote(sys.argv[1], safe=''))
PY
)"
  request_json \
    "GET /api/timeseries" \
    "${BACKEND_BASE}/api/timeseries?series=${SERIES_ENCODED}&from=${FROM_ISO}&to=${TO_ISO}" \
    "timeseries" || true
else
  echo "SKIP: GET /api/timeseries (no topics discovered)"
fi

if ((FAILURES > 0)); then
  echo "Smoke test failed with ${FAILURES} check(s) failing."
  echo "Artifacts: ${ARTIFACT_DIR}"
  exit 1
fi

echo "Smoke test passed."
exit 0
