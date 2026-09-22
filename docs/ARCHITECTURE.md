# System Architecture

This document describes the system as it actually exists in this
repository. Every section is labeled `CURRENT`, `PLANNED / FUTURE`, or
`NOT IMPLEMENTED` — nothing below the `CURRENT` label should be assumed
to exist in code. See `docs/ENGINEERING_STATUS.md` for verification
status of individual claims and `docs/RED_TEAM_REPORT.md` for known
weaknesses.

An earlier version of this document described a PostgreSQL + pgvector +
Redis + Celery + OIDC/SAML architecture. That was scaffolding from an
earlier design phase that was deliberately abandoned; SQLite was chosen
as the intentional product database (see `backend/app/core/config.py`,
which hardcodes it and comments *"Do not point this at PostgreSQL"*).
This rewrite replaces that description with the real one.

## 1. High-Level Architecture — `CURRENT`

- **Frontend**: Next.js 16 (App Router) + React 19 + Tailwind CSS 4.
  Server components fetch from the backend API at render time
  (`frontend/src/lib/api.ts`). No client-side state management library;
  no auth.
- **Backend API**: FastAPI (Python), single process. Routes live under
  `backend/app/api/`.
- **Ingestion scheduling**: `APScheduler`'s `BackgroundScheduler`, running
  **in-process** inside the FastAPI app (`backend/app/core/scheduler.py`),
  started from the app's `lifespan` handler. There is no separate worker
  process and no message broker — a 5-minute ticker evaluates which
  enabled sources are due (per source `polling_tier`: high=10min,
  medium=20min, low=60min, with exponential backoff on repeated failure)
  and runs ingestion synchronously within that scheduler thread.
- **Database**: SQLite, via SQLAlchemy. File-backed
  (`sqlite:///./ai_platform.db`) in normal operation; WAL journal mode,
  `busy_timeout=30000`, `synchronous=NORMAL`, `foreign_keys=ON` (set on
  every connection — `backend/app/db/session.py`). Tests use an in-memory
  SQLite engine.
- **LLM layer**: a provider-abstraction (`backend/app/core/providers/llm.py`)
  with concrete implementations for NVIDIA (the configured production
  provider — model `openai/gpt-oss-20b` via NVIDIA's OpenAI-compatible
  NIM endpoint), OpenAI, and Anthropic, plus a deterministic
  `TestLLMProvider` used only under `TESTING=1`/`TEST_MODE=1`, and a
  `FailClosedLLMProvider` that raises on every call when no production
  provider is configured. Production never silently substitutes
  `TestLLMProvider` — see `resolve_llm_mode()`/`get_llm_provider()`. All
  three real providers use the same manual JSON-schema-in-prompt +
  Pydantic-validation pattern (not SDK-specific structured-output
  helpers) and the same hard-wall-clock-deadline wrapper around every raw
  HTTP call (`call_with_hard_deadline`) — this uniformity was restored
  deliberately in Phase 1 after `OpenAIProvider` and `AnthropicProvider`
  were found to have real, independent SDK-compatibility bugs that made
  every real call to either of them crash; see
  `docs/RED_TEAM_REPORT.md` `OPENAI-BROKEN-01`. Only NVIDIA is exercised
  by a live-call test tier (gated behind `NVIDIA_API_KEY`); OpenAI/
  Anthropic are covered by tests that exercise the real SDK object
  against a fake transport, not a live endpoint (documented residual gap
  — see that finding's "neighboring attack" note).

There is no message broker, no worker pool, and no vector database in
the running system today. `backend/app/worker/` (Celery scaffolding) and
`backend/app/core/clustering.py` (a pgvector-based clustering function)
exist in the codebase but are **not on any code path the running
application actually executes** — see §6.

## 2. Ingestion Pipeline — `CURRENT`

Driven by `IntelligencePipeline.process_article()`
(`backend/app/core/pipeline.py`), invoked once per parsed RSS entry from
`scheduler.py::run_ingestion_cycle`:

1. **Normalize** — canonicalize the URL (`app/core/urls.py`,
   `app/core/deduplication.py::normalize_url`), reject anything without a
   safe http(s) URL and title.
2. **Deterministic noise filter** — regex-based clickbait patterns
   (`app/core/importance.py::is_obvious_noise`) reject before any LLM call.
3. **Enrich** — fetch and extract full article body / image / publisher
   name if the feed only provided a snippet (`app/core/article_body.py`),
   using the SSRF-hardened fetcher (§5).
4. **Deterministic dedup** — exact URL match (with same-URL-content-change
   handled as a new *version* that supersedes the old one, not an
   overwrite), then exact content-hash match (catches syndicated
   reposts), then a guarded Jaccard title-similarity fast path
   (`titles_are_safe_lexical_match`) that requires both high lexical
   overlap *and* a shared distinctive marker (product code, dollar
   amount, version number) and no *conflicting* marker, so "OpenAI raises
   $6.6B" cannot fast-merge with "OpenAI raises $6.6M".
5. **Classify** — one LLM call (`classify_event`) returns
   `event_kind`, `technical_change_scope`, `security_impact`,
   `primary_entities`/`mentioned_entities`, and a 1–100 importance score.
   The raw score is never trusted as-is: `calibrate_importance_score()`
   snaps it into a band implied by the structured signals (see
   `app/core/importance.py`), and deterministic signal inference
   (`infer_event_signals`) fills in anything the LLM omitted or backfills
   a kind the model defaulted to `other`.
6. **Semantic clustering** — for articles that didn't already match
   deterministically, candidate events from the last 48h are filtered by
   entity-name overlap (headline/summary/stored-entities substring match)
   and by `kinds_are_compatible()` (a small table of event-kind pairs that
   can *never* be the same real-world event — e.g. `funding` vs
   `model_release` — skipping an LLM call entirely for those). Only
   surviving candidates get an LLM relationship call
   (`classify_relationship`), which returns one of `SAME_EVENT`,
   `UPDATE_TO_SAME_EVENT`, `RELATED_EVENT`, `DIFFERENT_EVENT` — only
   `SAME_EVENT` triggers a merge.
7. **Summarize** — one LLM call (`summarize_event`) produces headline,
   short summary, what-changed bullets, and 1–3 verbatim citations.
   Citations are independently re-verified as exact (Unicode-normalized)
   substrings of the source article
   (`app/core/deduplication.py::verify_citations`) — the LLM's claim that
   a quote exists is never trusted on its own. If the model returned no
   verifiable quote, `fallback_source_citations()` copies (never
   paraphrases) 1–2 real source sentences that overlap the summary's own
   claim terms, and those are run back through the same verification.
8. **Persist** — inside a retry loop (SQLite lock contention under
   concurrent ingestion is expected and retried, bounded at 3 attempts),
   with a final late-match re-check taken *after* acquiring the SQLite
   write lock, since a competing worker may have created the canonical
   event while this one was waiting.

This is a synchronous, layered **entity-overlap + LLM-relationship**
approach, not embedding/vector clustering — see §6 for why the
vector-search code path exists but isn't used.

## 3. Data Integrity & Provenance — `CURRENT`

- **Versioning, not overwriting**: a same-URL content change creates a
  new `Event` row (`version` incremented) and sets `superseded_by_id` on
  the old row; the API always follows the chain to the live version
  (`IntelligencePipeline._live_event`).
- **Ingest source vs. originating source**: kept as two separate,
  never-conflated concepts. `app/core/origin.py::resolve_originating_source`
  only promotes an "official source" display when the ingest source is a
  known aggregator (Hacker News, Reddit, Google News), the article lives
  on a genuinely different host, *and* a publisher name was recovered
  from real page evidence (`og:site_name` meta tag or JSON-LD
  `publisher.name`) — never invented from the domain string. The API
  response (`EventResponse`) exposes `ingest_source` and
  `official_source` as distinct fields.
- **Source tiers**: `PRIMARY` / `SECONDARY` / `COMMUNITY`, stored per
  `Source` row (`backend/app/models/source.py`).

## 4. Frontend — `CURRENT`

- Server-rendered event feed (`frontend/src/app/(home)/page.tsx`) and
  event detail page (`frontend/src/app/events/[id]/page.tsx`), fetching
  directly from the FastAPI backend.
- A minimal, mostly-static admin sources page
  (`frontend/src/app/admin/sources/page.tsx`) that lists sources from the
  API — the "Add Source" and "Edit" controls currently render but are not
  wired to any action (`NOT IMPLEMENTED`, tracked in
  `docs/ENGINEERING_STATUS.md`).
- No authentication, no client-side routing library beyond Next's own,
  no design system package — Tailwind utility classes directly.

## 5. Security — `CURRENT` unless noted

- **SSRF**: `app/core/urls.py` blocks loopback/private/link-local/
  multicast/reserved/unspecified addresses (including IPv4-mapped IPv6),
  decimal/hex/short IP-literal tricks, dangerous URL schemes (including
  percent-encoded), credentials-in-URL, and a fixed blocked-port list.
  `app/core/fetcher.py` additionally resolves DNS once, rejects the whole
  host if *any* resolved address is blocked, and pins
  `socket.getaddrinfo` per-thread so the TCP connect cannot be redirected
  by a second DNS lookup after validation (DNS-rebinding TOCTOU
  mitigation) — re-validated independently per redirect hop, capped at 5
  hops, with a response-size ceiling (2MB).
- **Prompt injection**: article content is always wrapped in
  `<article>...</article>` tags with an explicit system-prompt
  instruction to treat that content as untrusted data, never as
  instructions. `TestLLMProvider` has a deterministic canary
  (`"IGNORE ALL PREVIOUS INSTRUCTIONS"` → forced score 0) for fast tests;
  live resistance is additionally exercised against the real NVIDIA
  provider in `backend/tests/test_prompt_injection_semantic.py`.
- **LLM output validation**: every provider response is parsed through
  Pydantic schemas (`EventClassification`, `SourceGroundedSummary`,
  `RelationshipResult`); malformed/unparseable output is treated as "no
  usable result" (returns `None`, does not crash or fabricate a fallback
  value), not coerced into something that looks valid.
- **CORS**: currently `allow_origins=["*"]` with `allow_credentials=True`
  in `backend/app/main.py` — an open finding, see
  `docs/RED_TEAM_REPORT.md` (`CORS-01`). Low practical impact today since
  no cookie/session auth exists, but flagged as a real issue to fix, not
  a "PLANNED" item to defer indefinitely.
- **Authentication / authorization**: `NOT IMPLEMENTED`. No OIDC, no
  SAML, no session/cookie auth, no roles. The admin sources page and
  every API endpoint are unauthenticated.
- **Log secret redaction**: `app/core/logger.py::RedactSecretsFilter`
  strips known credential shapes (NVIDIA/OpenAI/Anthropic API key
  prefixes, `Authorization`/`Bearer`/`Cookie` headers, generic
  `api_key=`/`token=`/`secret=` kwargs) from every log line before it
  reaches a handler. Added after a real incident — see
  `docs/RED_TEAM_REPORT.md` (`SECRET-EXPOSURE-01`).

## 6. Code paths that exist but are not reachable — `NOT IMPLEMENTED` / dead

Kept in the repo, clearly labeled here rather than silently removed,
since they represent real future-upgrade thinking:

- **`backend/app/core/clustering.py`** — cosine-similarity event matching
  against `pgvector` embeddings. Its own docstring says it is *"NOT
  called by the primary pipeline, which uses a layered entity + LLM
  approach instead."* It only activates if the `pgvector` package is
  importable, which it never is under the SQLite-only configuration this
  product actually runs (`backend/app/models/event.py` falls back to a
  plain `JSON` column for `embedding` when `pgvector` isn't available,
  and nothing ever populates that column). This is a legitimate future
  upgrade path if/when the event volume justifies vector search over the
  current entity+LLM approach — not a bug, but currently 100% dead code.
- **`backend/app/worker/`** (`celery_app.py`, `tasks.py`) — Celery
  scaffolding. Nothing in the running application enqueues a Celery task;
  ingestion runs synchronously inside the APScheduler thread instead (§1).
- **Redis** — referenced in `Settings.REDIS_URL`
  (`backend/app/core/config.py`) for the unused Celery broker. Not
  connected to anything at runtime.

## 7. Deployment — `PARTIALLY IMPLEMENTED`

- `backend/Dockerfile` builds the FastAPI backend as a container.
- Root `docker-compose.yml` currently reflects the real system: backend
  (SQLite, volume-mounted for the db file) + frontend, no Postgres/Redis/
  Celery services. (This file was rewritten alongside this document —
  see `docs/ENGINEERING_STATUS.md`, `DOC-01`, for what it looked like
  before.)
- No CI/CD pipeline, no production hosting configuration, no secrets
  manager integration beyond reading environment variables
  (`backend/app/core/config.py` also opportunistically hydrates from
  Windows user/machine environment variables via the registry, for local
  dev convenience — `_hydrate_os_environ`).

## 8. Planned / future directions — `PLANNED / FUTURE`, not started

Documented here as legitimate future possibilities, not as things that
exist:

- **Vector-based clustering** (§6) if entity+LLM matching stops scaling
  or precision degrades at higher article volume — the `pgvector` code
  path already sketches the shape of this.
- **Horizontal scaling** (separate worker process(es), a real message
  broker) if a single in-process APScheduler thread becomes an ingestion
  throughput bottleneck. Postgres would likely accompany this move, since
  SQLite's single-writer model is the natural ceiling — but that is a
  scaling decision to make if and when the current SQLite-based system
  actually hits its limits, not a default to reach for.
- **Authentication / RBAC** for the admin surface, if/when this stops
  being a single-operator local tool.
