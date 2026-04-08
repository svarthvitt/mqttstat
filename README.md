# mqttstat

A clean, service-oriented starter layout for mqttstat with dedicated backend, frontend, and infrastructure folders.

## Project structure

```text
.
├── backend/             # FastAPI API service
│   ├── app/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/            # React app (Vite)
│   ├── src/
│   ├── Dockerfile
│   └── package.json
├── infra/               # Compose-adjacent infra files
│   ├── db/init/
│   └── migrations/
├── docs/                # Architecture + extension docs
├── docker-compose.yml   # Root local orchestration
└── .env.example         # Environment variable template
```

## Local setup

1. Copy environment variables:

   ```bash
   cp .env.example .env
   ```

2. Build and start services:

   ```bash
   docker compose up --build
   ```

3. Stop services:

   ```bash
   docker compose down
   ```

## Service URLs

- Frontend (React dev server): `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Backend health check: `http://localhost:8000/health`
- PostgreSQL: `localhost:5432`

## Notes

- Backend and frontend use separate Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`).
- DB initialization SQL is in `infra/db/init/`.
- Future migration scripts belong in `infra/migrations/`.
- Additional project documentation is in `docs/`.
