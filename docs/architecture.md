# Architecture Overview

Top-level layout:

- `backend/` – FastAPI service exposing API endpoints.
- `frontend/` – React (Vite) web client.
- `infra/` – Infrastructure artifacts (compose resources, DB init, migrations).
- `docs/` – Project documentation.

## Runtime services

- `backend` (FastAPI) on `http://localhost:8000`
- `frontend` (React dev server) on `http://localhost:5173`
- `db` (PostgreSQL) on `localhost:5432`

## Data flow

1. Browser loads the frontend.
2. Frontend calls backend API.
3. Backend reads/writes PostgreSQL.
