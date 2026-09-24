# AI World Intelligence Platform

The homepage is a current-week market overview: what is happening now, what is trending, the largest developments, category activity, and major AI organizations. The chronological week feed stays underneath. Newest developments are first. Repeated reports of the same release collapse into one event. Official and research links come from the articles the pipeline actually fetched.

Stack: FastAPI, SQLite, APScheduler, Next.js. There is no Postgres, Redis, or Celery in the running system.

## Prerequisites

- Python 3.12
- Node.js 20 or newer
- An LLM API key if you want ingestion. `LLM_PROVIDER=nvidia` and `NVIDIA_API_KEY` are the default. The site still serves events already in the database when the key is missing. It does not fall back to a test model.

## Fresh setup

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

cd frontend
npm install
cd ..

copy backend\.env.example backend\.env
# Put NVIDIA_API_KEY in backend\.env if you want ingestion.

copy frontend\.env.example frontend\.env.local
# Set NEXT_PUBLIC_API_BASE_URL if the API is not on http://localhost:8000.
```

On bash, use `source .venv/bin/activate` and `cp` instead of `copy`.

Initialize the database and the curated sources:

```powershell
cd backend
python seed_sources.py
```

`seed_sources.py` creates the SQLite tables if they are missing and loads `sources.registry.json`. Starting the API also creates tables. You do not need a checked-in database file.

## Run

Two terminals, both from the repository after the virtualenv is active.

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm run dev
```

Open http://localhost:3000. Health check: http://127.0.0.1:8000/api/health.

The scheduler starts with the API and polls enabled RSS sources every 5 minutes, subject to each source's polling tier. One failing feed does not stop the others.

## Development checks

```powershell
cd backend
python -m pytest -q -m "not live_nvidia"
```

`live_nvidia` tests call the real NVIDIA API. They are skipped by that marker even when `NVIDIA_API_KEY` is set.

```powershell
cd frontend
npx tsc --noEmit
npm run lint
npm test
npm run build
```

## Sources

Adding a feed is a data change. See `docs/SOURCE_REGISTRY.md`.

```powershell
cd backend
python manage_sources.py list
python manage_sources.py add --organization "OpenAI" --name "OpenAI Research" --url "https://example.com/feed.xml" --tier research
python manage_sources.py disable --name "OpenAI Research"
python manage_sources.py enable --name "OpenAI Research"
python manage_sources.py update --name "OpenAI Research" --url "https://example.com/new.xml"
python manage_sources.py ingest
python manage_sources.py repair-headlines          # dry run
python manage_sources.py repair-headlines --apply  # keeps the original in importance_reasoning
python manage_sources.py repair-versions            # dry run; --apply to repair
```

`ingest` runs one cycle immediately. Otherwise the running scheduler picks up an enabled row on the next tick. Disabled rows are not fetched. Re-running `seed_sources.py` updates curated URLs and does not re-enable a source you disabled.

## Data, logs, reset

- Database file: `backend/ai_platform.db` (override with `DATABASE_URL`). SQLite WAL files `*.db-wal` and `*.db-shm` sit beside it. They are gitignored.
- WAL is turned on for every connection, with a 30 second busy timeout, so a read can proceed while a source is being written.
- Logs go to the API process stdout. API keys are not written to those logs.
- Reset development data by stopping the API and deleting `backend/ai_platform.db` (and the `-wal` / `-shm` files), then run `python seed_sources.py` again.
- Copy the `.db` file while the API is stopped if you need a backup.

## Configuration

`backend/.env.example` lists every setting. Required for ingestion: `LLM_PROVIDER` and that provider's key. `DATABASE_URL` and `CORS_ALLOWED_ORIGINS` have local defaults. `TESTING=1` is development-only and selects the deterministic test provider. Do not set it in production.

`frontend/.env.example` sets `NEXT_PUBLIC_API_BASE_URL`.

## Layout

| Path | Role |
|---|---|
| `backend/app` | API, scheduler, ingestion, providers |
| `backend/sources.registry.json` | Curated feeds |
| `backend/manage_sources.py` | Add, enable, disable, update, ingest once |
| `frontend/src` | Week feed and event pages |
| `docs/ARCHITECTURE.md` | How the running system is put together |
| `docs/SOURCE_REGISTRY.md` | How to add a source |
| `docs/INGESTION.md` | Fetch and schedule behavior |
| `docs/DATA_MODEL.md` | Tables |

`docs/RED_TEAM_REPORT.md` and the two root research markdown files are historical notes. They are not operating instructions.
