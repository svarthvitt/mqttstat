# Extension Guide

## Backend

- Add routes in `backend/app/main.py` or split into routers under `backend/app/routers/`.
- Add dependencies to `backend/requirements.txt`.

## Frontend

- Add UI modules under `frontend/src/`.
- Configure API base URL with `VITE_API_BASE_URL`.

## Infrastructure

- Add migration scripts to `infra/migrations/`.
- Extend `docker-compose.yml` for supporting services (MQTT broker, Redis, etc.).
