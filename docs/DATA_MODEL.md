# Data Model

Transcribed directly from the actual SQLAlchemy models
(`backend/app/models/`) — this document should be regenerated from code
whenever the models change, not hand-maintained independently of it.
Labels: `CURRENT`, `PLANNED / FUTURE`, `NOT IMPLEMENTED`.

## Core Entities — `CURRENT`

### `Source` (`backend/app/models/source.py`)
- `id` (UUID, PK)
- `name` (String)
- `url` (String, unique)
- `organization_id` (UUID, FK → `Organization`, nullable)
- `type` (String, default `"rss"`) — free text; only `"rss"` is actually
  fetched (see `docs/INGESTION.md`)
- `tier` (String, default `"secondary"`) — `primary` | `secondary` | `community`
- `polling_tier` (String, default `"medium"`) — `high` | `medium` | `low`
- `enabled` (Boolean, default `True`)
- `health_status` (String, default `"healthy"`) — `healthy` | `degraded` | `failing` | `disabled`
- `last_error_info` (String, nullable)
- `consecutive_failures` (Integer, default 0)
- `last_fetch_at`, `last_failure_at` (DateTime, nullable)
- `last_ingest_summary` (String, nullable) — compact per-cycle counters,
  e.g. `"discovered=12 created=3 linked=2 rejected=6 duplicates=1 llm_errors=0"`
- `created_at`, `updated_at` (DateTime, server-default now)

Note: flat columns, not a `polling_policy`/`health_status` JSON blob —
each concern is its own indexable column.

### `Organization` (`backend/app/models/source.py`)
- `id` (UUID, PK)
- `name` (String, unique)
- `domain` (String, nullable)

### `Article` (`backend/app/models/article.py`) — raw ingested content
- `id` (UUID, PK)
- `source_id` (UUID, FK → `Source`)
- `url` (String, unique)
- `title` (String)
- `raw_content` (Text, nullable)
- `body_excerpt` (String(500), nullable) — first ~500 chars, used for
  quick display/debugging
- `published_at` (DateTime, nullable) — source-declared publish time
- `ingested_at` (DateTime, server-default now) — when this row was inserted
- `hash` (String, indexed) — SHA-256 of normalized content, used for
  syndicated-duplicate detection
- `image_url`, `publisher_name` (String, nullable) — recovered during
  enrichment (`app/core/article_body.py`)

### `Event` (`backend/app/models/event.py`) — the core synthesized object
- `id` (UUID, PK)
- `headline` (String)
- `short_summary` (String)
- `what_changed` (Text, nullable)
- `importance_score` (Integer, default 0)
- `importance_reasoning` (JSON, nullable) — `{text, event_kind, scope, security_impact}`
- `entities` (JSON list, default `[]`) — primary entities (1–6, what the event is ABOUT)
- `mentioned_entities` (JSON list, default `[]`) — additional named entities
- `citations` (JSON list, default `[]`) — verbatim, source-verified quotes
- `image_url` (String, nullable)
- `article_url` (String, nullable) — canonical clean article URL
- `official_source_name` (String, nullable) — only set when
  `resolve_originating_source` confidently identified a non-ingest
  publisher (see `docs/ARCHITECTURE.md` §3)
- `event_time` (DateTime, indexed, nullable) — real-world occurrence time
  (falls back to `created_at` in the API/UI, never overwritten)
- `embedding` (JSON, nullable) — `pgvector.Vector` type only if `pgvector`
  is importable *and* the DB isn't SQLite; always falls back to plain
  `JSON` in this product's actual SQLite configuration, and nothing
  currently writes to this column (see `docs/ARCHITECTURE.md` §6)
- `primary_source_id` (UUID, FK → `Source`, nullable)
- `version` (Integer, default 1) — incremented on a same-URL content
  update that supersedes an earlier version
- `superseded_by_id` (UUID, FK → `Event`, self-referential, nullable) —
  set on the *old* row when a newer version supersedes it; the API always
  follows this chain to the live version
- `created_at` (DateTime, server-default now, indexed) — ingestion time
- `updated_at` (DateTime, server-default now, onupdate now)

There is **no separate `why_it_matters` field** — deliberately removed;
the summarization prompt explicitly forbids editorial "why it matters"
commentary (see `docs/ARCHITECTURE.md` §2, step 7). An earlier version of
this document still listed the field; that was stale, not a
still-planned addition.

There is **no separate `EventVersion` audit table** — versioning is the
`version` + `superseded_by_id` pair directly on `Event`, not a JSONB
snapshot log.

### `EventArticle` (`backend/app/models/event.py`) — join table
- `event_id` (UUID, FK → `Event`, part of composite PK)
- `article_id` (UUID, FK → `Article`, part of composite PK)
- `similarity_score` (Float, nullable) — not currently populated by the
  entity+LLM pipeline (would be relevant to the vector-clustering future
  path in §6 of the architecture doc)
- `link_type` (String, default `"supporting"`) — `primary` | `supporting` | `additional`

## Not implemented (do not assume these tables exist)

- **`Entity` / `EventEntity`** normalized tables — entities are stored
  directly as JSON string lists on `Event` (`entities`,
  `mentioned_entities`), not as rows in a separate entity table with a
  join. No entity-resolution/aliasing table exists (e.g. nothing ties
  "GPT-4" and "GPT4" together beyond the case-insensitive dedup in
  `app/core/entities.py`).
- **`User` / `SavedEvent`** — no user accounts, auth, roles, or
  bookmarking exist anywhere in the schema. See `docs/ARCHITECTURE.md`
  §5 for the authentication status.

## Planned / future

- An `Entity`/`EventEntity` normalized model, if/when cross-event entity
  analytics (e.g. "show me everything about OpenAI") need to be more than
  a JSON-array substring match.
- `User`/`SavedEvent`, if/when this stops being a single-operator tool.
