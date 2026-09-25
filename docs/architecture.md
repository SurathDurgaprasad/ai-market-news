# Architecture

AI Market News is two processes and one database file:

```
┌──────────────────────────── backend (one Python process) ───────────────────────────┐
│                                                                                      │
│  APScheduler (every 5 min)            FastAPI                                        │
│        │                                 │  /api/v1/events, /overview, /sources      │
│        ▼                                 │  /api/v1/events/{id}/image                │
│  ingestion pipeline ──── writes ──► SQLite (WAL) ◄──── reads ──┘                     │
│        │                                                                             │
│        └── language-model provider (OpenAI / NVIDIA / Anthropic / Bedrock)           │
└──────────────────────────────────────────────────────────────────────────────────────┘
                                          ▲
                                          │ HTTP (server-side rendering, image URLs)
                               ┌──────────┴──────────┐
                               │ Next.js frontend    │
                               └─────────────────────┘
```

There is no message broker, worker pool, cache server or separate database server. The scheduler runs inside the API process; SQLite is a single file.

## The product object: the canonical event

Articles are evidence. The product object is the **canonical event**: one real-world development, such as a model release, a funding round or a security incident.

```
Event  (one development: headline, summary, what changed, category, importance, entities, verified quotes)
 ├── Article (primary)      the source the event was built from
 ├── Article (supporting)   other coverage of the same development
 └── previous versions      earlier states when a source page changed materially
```

| Table | Holds |
|---|---|
| `event` | The canonical event. `superseded_by_id` points a merged duplicate or an older version at the live event. `importance_reasoning` keeps the structured classification (kind, scope, security impact, market category). |
| `article` | One fetched URL: raw text (kept in full), content hash, publisher, image, enrichment status (`pending` while the provider is unavailable, `rejected` when out of scope). |
| `event_article` | Links articles to events as `primary` or `supporting`. |
| `source` | A feed in the registry: URL, tier, polling tier, enabled flag, health and failure history. |
| `organization` | The organization a source belongs to. |

Invariants the pipeline maintains, and the tests check: one live event per development; every live event has a primary article; an article belongs to at most one live event; no pending or rejected article is attached to a live event; merge chains never dangle or loop.

## Ingestion pipeline

```
SOURCE (RSS/Atom feed in the registry)
  ↓  fetch, only when due for its polling tier
SECURITY VALIDATION   public http(s) only, DNS pinned, redirects re-checked, size and decompression caps
  ↓
NORMALIZE / EXTRACT   canonical URL, clean text from hostile HTML, full article body when the feed has a snippet
  ↓
DEDUPLICATE           same URL (edits become versions), same content hash, guarded title match
  ↓
CLASSIFY              LLM: kind, scope, security impact, market area, entities, importance (then calibrated)
  ↓
RELATIONSHIP ANALYSIS LLM, only against the few most similar recent events: same event, update, related, different
  ↓
SUMMARIZE             LLM: headline, summary, what changed, quotes
  ↓
EVIDENCE CHECK        every quote must exist verbatim in the source text, or it is dropped
  ↓
CANONICAL EVENT       new event, or the article attached to an existing one as supporting coverage
  ↓
SQLITE → API → WEB UI
```

Details: [ingestion.md](ingestion.md) (scheduling, outages, deduplication) and [intelligence.md](intelligence.md) (classification, categories, evidence).

When the provider is unavailable, articles are still fetched and stored as `pending`, and enriched once it recovers. Nothing is invented without the model.

## Backend layout

| Path | Role |
|---|---|
| `backend/app/main.py` | FastAPI app, CORS, health endpoint, scheduler start and stop |
| `backend/app/api/endpoints/` | `events.py` (feed, overview, detail, image), `sources.py` (source health) |
| `backend/app/core/scheduler.py` | Polling schedule, backoff, outage cooldown, pending retries |
| `backend/app/core/pipeline.py` | `IntelligencePipeline.process_article`: one article through every stage |
| `backend/app/core/fetcher.py`, `urls.py` | SSRF-hardened HTTP fetching and URL sanitization |
| `backend/app/core/parser.py`, `article_body.py` | Feed parsing and article-body extraction |
| `backend/app/core/deduplication.py` | Deterministic matching, evidence validation, prompt-injection quarantine |
| `backend/app/core/providers/llm.py` | Provider abstraction, prompts, retries, deadlines |
| `backend/app/core/market.py` | Categories, trending, pulse and players for the overview |
| `backend/app/core/digest.py` | Newsletter digests: use only the lead story |
| `backend/app/core/thumbnails.py` | Resized, cached event images |
| `backend/app/core/llm_usage.py` | Per-request usage ledger |
| `backend/app/models/` | SQLAlchemy models |
| `backend/manage_sources.py` | Operator CLI: sources, ingestion, maintenance jobs, usage |
| `backend/sources.registry.json` | The curated source list loaded by `seed_sources.py` |

## Frontend layout

Next.js App Router with server components; pages fetch from the API at request time.

| Route | Page |
|---|---|
| `/` | Homepage: trending strip, what's happening now (lead + secondary stories), biggest developments, latest developments, market pulse and major players |
| `/events/[id]` | Event page: headline, summary, image, what changed, verified quotes, entities, related developments, sources and update history |
| `/players/[slug]` | This week's developments for one organization |
| `/admin/sources` | Source health |

`frontend/src/proxy.ts` answers unknown or malformed event IDs with a real 404 and redirects merged duplicates to their canonical event before a page renders.

## API

Read-only. Event and source routes are under `/api/v1`; interactive documentation is at `/docs` on the running API.

| Endpoint | Returns |
|---|---|
| `GET /events/` | Live events, newest first. `scope=week`, `player=<slug>`, `q`, `min_importance`, `skip`, `limit` (max 250) |
| `GET /events/overview` | Now, trending, biggest, pulse, players and ingestion status |
| `GET /events/{id}` | One event with sources, related events and versions |
| `GET /events/{id}/resolve` | Canonical ID for a possibly merged event |
| `GET /events/{id}/image?w=192\|640\|1200` | The event image as a resized WebP |
| `GET /events/new_count?since=<ISO time>` | Number of events recorded since then |
| `GET /sources/` | Source registry with health |
| `GET /api/health` (not under `/api/v1`) | Provider mode, scheduler state, enrichment pause |

## Times

All timestamps are stored and displayed in UTC. "This week" starts Monday 00:00 UTC; "now" is the last 36 hours.
