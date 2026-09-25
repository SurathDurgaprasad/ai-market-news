# AI Market News

[![CI](https://github.com/SurathDurgaprasad/AI-Market-News/actions/workflows/ci.yml/badge.svg)](https://github.com/SurathDurgaprasad/AI-Market-News/actions/workflows/ci.yml)

AI Market News continuously collects important AI developments from multiple sources, consolidates coverage of the same real-world development, and presents the result as a clean, readable AI news and market-intelligence website.

Open the homepage and see what is happening in AI right now: the biggest developments, what is trending, which areas of AI are active, who is involved, and where to read the original sources.

```
ONE REAL-WORLD DEVELOPMENT  →  ONE CANONICAL EVENT  →  MULTIPLE SUPPORTING SOURCES
```

A lab's announcement, the news story about it and the discussion thread are one development, shown once, with every source attached as evidence.

## Key capabilities

| | |
|---|---|
| **Source ingestion** | Polls a curated registry of RSS/Atom feeds (official lab blogs, research, news, community) on per-source schedules, with backoff for failing feeds. |
| **Canonical events** | Deterministic URL, content and title checks, then a model relationship check, merge repeated coverage into one event. Page edits become versions, not duplicates. |
| **AI-assisted analysis** | A language model classifies each development (kind, market area, importance, entities) and writes a short, source-grounded summary. |
| **Evidence and provenance** | Every quote shown is verified verbatim against the source text. Official sources, research papers, news coverage and discussion are labelled as such. |
| **Editorial UI** | Lead story, trending areas, biggest developments, market pulse, major players and a dense latest feed; event pages read like an article dossier. |
| **Security** | SSRF-hardened fetching, hostile-HTML handling, prompt-injection boundaries, secret redaction in logs, and tests that never call a paid API. |
| **Cost control** | Per-request usage ledger, bounded and batched maintenance jobs with an estimate before any call, and no retries on exhausted quota. |

Market areas: **Models, Agents, Coding, Research, Security, Hardware, Infrastructure, Robotics, Multimodal, Open Source, Policy, Funding, Partnerships.** A development that fits none of them is left uncategorized rather than forced into one.

## Architecture

```
RSS/Atom sources ─► fetch (SSRF-guarded) ─► extract & clean ─► deduplicate
      ─► classify (LLM) ─► relationship check (LLM) ─► summarize + verify evidence (LLM)
      ─► canonical event + supporting articles ─► SQLite ─► FastAPI ─► Next.js
```

| Layer | Technology |
|---|---|
| Backend API and ingestion | Python 3.12, FastAPI, SQLAlchemy, APScheduler (in process) |
| Database | SQLite (one file, WAL mode) |
| Language models | Provider abstraction: OpenAI (default), NVIDIA, Anthropic, Amazon Bedrock |
| Frontend | Next.js 16, React 19, Tailwind CSS 4 |

There is no message broker, worker pool or separate database server. See [docs/architecture.md](docs/architecture.md).

## Prerequisites

**Required**

| Tool | Version | Source of truth |
|---|---|---|
| Python | 3.12 | `.python-version`, `backend/Dockerfile` |
| Node.js | 20.9 or newer | Next.js 16 engine requirement |
| npm | bundled with Node (lockfile v3) | `frontend/package-lock.json` |
| SQLite | bundled with Python | no separate install |

**Optional: a language-model provider**, needed only for ingesting new articles. Without one, the site still serves stored developments.

| Provider | `LLM_PROVIDER` | Needs |
|---|---|---|
| OpenAI | `openai` (default) | `OPENAI_API_KEY` |
| NVIDIA NIM | `nvidia` | `NVIDIA_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`, `pip install anthropic` |
| Amazon Bedrock | `bedrock` | AWS credentials and region, `BEDROCK_MODEL_ID`, `pip install boto3` |

Credentials belong in your environment or an untracked `backend/.env`. They are never committed.

## Quick start

```bash
git clone https://github.com/SurathDurgaprasad/AI-Market-News.git
cd AI-Market-News

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then set LLM_PROVIDER and its key
python seed_sources.py             # load the curated source registry
uvicorn app.main:app --port 8000

# Frontend (second terminal)
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. API health: http://127.0.0.1:8000/api/health.

The API creates the SQLite database on first start and the scheduler begins polling due sources. Developments appear as articles are enriched, usually within a few minutes. Without a provider key the site still runs and says so, but no new developments are created.

## Everyday commands

| Task | Command (from `backend/` unless noted) |
|---|---|
| Backend tests (never call a real API) | `python -m pytest -q` |
| Frontend tests, typecheck, lint, build | `cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build` |
| List / add / disable sources | `python manage_sources.py list` · `add` · `disable` · `enable` · `update` |
| Run one ingestion cycle now | `python manage_sources.py ingest` |
| Language-model usage so far | `python manage_sources.py llm-usage --hours 24` |
| Serve stored data only (no ingestion) | `SCHEDULER_ENABLED=0 uvicorn app.main:app --port 8000` |

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Setup, demo data, first ingestion |
| [Architecture](docs/architecture.md) | Components, data model, request flow |
| [Configuration](docs/configuration.md) | Every environment variable |
| [Ingestion](docs/ingestion.md) | Scheduling, fetching, deduplication, outages |
| [Sources](docs/sources.md) | The source registry and its commands |
| [Intelligence](docs/intelligence.md) | Providers, classification, categories, evidence, cost controls |
| [Security](docs/security.md) | Protections and how secrets are handled |
| [Testing](docs/testing.md) | Test suites, live-provider tests, CI |
| [Deployment](docs/deployment.md) | Running in production, Docker |
| [Troubleshooting](docs/troubleshooting.md) | Common problems |
| [Contributing](docs/contributing.md) | How to contribute |

## Security

Report vulnerabilities privately; see [SECURITY.md](SECURITY.md). Never put API keys in issues, pull requests, logs or commits.

## License

No license has been chosen yet. Until one is added, the code is published for reading and evaluation only, and the default copyright rules apply: you may not copy, modify or redistribute it without the owner's permission.
