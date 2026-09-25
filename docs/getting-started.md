# Getting started

This guide takes a fresh clone to a running site. Commands use a POSIX shell; Windows equivalents are noted where they differ.

## 1. Requirements

- Python 3.12
- Node.js 20.9 or newer, with npm
- An API key for one supported language-model provider, if you want new developments to be ingested (see [configuration.md](configuration.md#language-model-provider)). The site runs without one, but only serves what is already stored.

## 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
```

Edit `backend/.env` and set the provider, for example:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=<your key>
```

`backend/.env` is ignored by git. Do not commit it, and do not paste keys into issues or logs.

Load the curated sources and start the API:

```bash
python seed_sources.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On start the API creates `backend/ai_platform.db` if needed and starts the in-process scheduler. Check it:

```bash
curl http://127.0.0.1:8000/api/health
```

`llm_mode` is `production` when a provider is configured, and `unavailable` when it is not.

## 3. Frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. The frontend calls the API at `http://localhost:8000` unless `NEXT_PUBLIC_API_BASE_URL` is set (copy `frontend/.env.example` to `frontend/.env.local` to change it).

## 4. First developments

The scheduler checks every 5 minutes which sources are due. To run one cycle immediately:

```bash
cd backend
python manage_sources.py ingest
```

Each new article is fetched, checked against existing events, classified and summarized. Expect a few provider requests per new article; see [intelligence.md](intelligence.md#cost-controls). The homepage shows the current week (Monday 00:00 UTC onward).

## 5. Serving stored data only

To browse stored developments without fetching sources or calling a provider (for UI work or a read-only copy):

```bash
SCHEDULER_ENABLED=0 uvicorn app.main:app --port 8000      # Windows PowerShell: $env:SCHEDULER_ENABLED="0"; uvicorn ...
```

`/api/health` then reports `"scheduler_enabled": false`.

## Next steps

- Add or disable sources: [sources.md](sources.md)
- Run the tests: [testing.md](testing.md)
- Deploy: [deployment.md](deployment.md)
