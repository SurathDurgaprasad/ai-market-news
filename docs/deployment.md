# Deployment

AI Market News is a single backend process with a SQLite file, plus a Next.js frontend. It suits a single server or a small VM.

## Backend

Run one API process. The scheduler runs inside it, and more than one process would poll sources twice and compete for SQLite writes.

```bash
cd backend
pip install -r requirements.txt
python seed_sources.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Put `backend/ai_platform.db` (or the path in `DATABASE_URL`) on persistent storage, and back it up by copying the file while the API is stopped.
- Provide the provider key through the environment or a secrets manager, never a committed file.
- Set `CORS_ALLOWED_ORIGINS` to the frontend's real origin.
- Put a reverse proxy with TLS in front of the API. The API is read-only and unauthenticated; expose only what the frontend and browsers need (`/api/v1/*`).
- `backend/logs/` (usage ledger) and `backend/image_cache/` grow over time; both are safe to rotate or delete.

For a read-only replica or a UI review, run with `SCHEDULER_ENABLED=0`.

## Docker (backend)

`docker-compose.yml` builds and runs the backend with the database in a named volume:

```bash
export OPENAI_API_KEY=…            # from your secrets store; never write it into a tracked file
docker compose up --build -d
docker compose exec backend python seed_sources.py
```

The image runs as a non-root user and excludes `.env` files, databases, logs and caches from its build context. The frontend is not containerized; run it as below.

## Frontend

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE_URL=https://api.example.com npm run build
npm start                              # serves on port 3000
```

`NEXT_PUBLIC_API_BASE_URL` is embedded in the build, and browsers load event images from it, so it must be the API's public URL. Rebuild after changing it.

## Health and monitoring

- `GET /api/health`: `llm_mode`, `scheduler_enabled`, `enrichment_paused`.
- `GET /api/v1/sources/`: per-source health and last result.
- `python manage_sources.py llm-usage --hours 24`: provider requests, failures and tokens.
