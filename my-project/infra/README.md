# Infrastructure

Docker Compose and deployment configuration for local development and production.

## Services

- `backend` — FastAPI API server
- `frontend` — Vite dev server / static build
- `worker` — Celery background worker
- `postgres` — PostgreSQL with pgvector
- `redis` — Celery broker and result backend

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

## Files

- `docker-compose.yml` — Service orchestration
- `Dockerfile.backend` — Backend container
- `Dockerfile.frontend` — Frontend container
- `Dockerfile.worker` — Worker container
- `postgres-init.sql` — Database initialization (pgvector extension)
- `.env.example` — Environment variable template
