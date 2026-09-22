# Implementation Roadmap

Rewritten to reflect actual status (see `docs/ENGINEERING_STATUS.md` for
verification detail on each claim below). The previous version of this
file had every item unchecked despite most of Phases 1–7 being
substantially built — that undersold real progress and should not be
trusted as a status source going forward; `docs/ENGINEERING_STATUS.md`
is now the living status document.

## PHASE 0: Requirements / Architecture — DONE
- [x] Core documentation (this repo's `docs/`), now corrected to
  describe the actual SQLite + APScheduler + provider-abstraction system
  rather than the originally-planned Postgres/pgvector/Redis/Celery/OIDC
  stack (see `docs/ARCHITECTURE.md`).

## PHASE 1: Source Registry + Ingestion — DONE (RSS only)
- [x] FastAPI backend environment.
- [x] Database schemas (SQLAlchemy + Alembic migrations,
  `backend/alembic/versions/`).
- [x] Data-driven `Source`/`Organization` registry models.
- [x] RSS fetcher + APScheduler-based scheduling (`docs/INGESTION.md`).
- [ ] GitHub / generic API fetchers — `NOT IMPLEMENTED` (source `type`
  accepts these values but nothing processes them yet).

## PHASE 2: Deduplication + Event Intelligence — DONE, different mechanism than originally planned
- [x] Deterministic dedup (URL, content hash, guarded title-Jaccard
  fast path — `backend/app/core/deduplication.py`).
- [x] Event-relationship clustering — **not** embedding/pgvector-based as
  originally planned. Uses layered entity-name overlap +
  incompatible-kind filtering + an LLM relationship call
  (`SAME_EVENT`/`UPDATE_TO_SAME_EVENT`/`RELATED_EVENT`/`DIFFERENT_EVENT`)
  instead. See `docs/ARCHITECTURE.md` §2 and §6 for why.
- [x] Article-to-event merge logic, including same-URL content-update
  versioning (`superseded_by_id` chain).
- [ ] Vector-embedding clustering — `PLANNED / FUTURE` if entity+LLM
  matching stops scaling; the pgvector code path exists but is unused
  (`backend/app/core/clustering.py`).

## PHASE 3: AI Enrichment — DONE
- [x] Provider-abstracted LLM integration (NVIDIA production provider,
  OpenAI/Anthropic alternates, strict Pydantic structured-output
  validation with multi-mode JSON-extraction fallback for NVIDIA).
- [x] Source-grounded summarization with independent citation
  verification (exact substring match against the source, not trusted
  from the LLM).
- [x] Structured importance scoring: LLM score + deterministic
  calibration bands by event kind/scope/security-impact — not a raw
  LLM number trusted as-is.

## PHASE 4: Storage + Search — DONE (SQLite, not Postgres)
- [x] SQLite with WAL mode, busy-timeout, retry-on-lock-contention in
  the pipeline's persist step — a deliberate choice, not an unfinished
  Postgres migration (see `backend/app/core/config.py`'s comment: *"Do
  not point this at PostgreSQL"*).
- [x] Keyword search (`q` param, `ilike` across headline/summary/
  what_changed), `min_importance` filter, `organization_id` filter,
  pagination.
- [ ] Source-tier and date-range filtering — `NOT IMPLEMENTED` at the API
  level (tier and event_time are stored and returned, but not exposed as
  filter query params yet).

## PHASE 5: Dashboard — DONE
- [x] Next.js 16 + Tailwind CSS 4 frontend.
- [x] High-information-density feed (`frontend/src/app/(home)/page.tsx`).
- [x] Event detail view with provenance/evidence
  (`frontend/src/app/events/[id]/page.tsx`).

## PHASE 6: Organization / Auth / Admin — MOSTLY NOT IMPLEMENTED
- [ ] Authentication (OIDC/JWT or otherwise) — `NOT IMPLEMENTED`. No auth
  exists anywhere in the system today; this is a real gap, not merely
  deferred detail.
- [ ] Admin event splitting/merging UI — `NOT IMPLEMENTED`.
- [x] Basic admin source listing/health display
  (`frontend/src/app/admin/sources/page.tsx`) — read-only.
- [x] "New Since Last Visit" tracking (`/api/v1/events/new_count`).

## PHASE 7: Security & Reliability Hardening — SUBSTANTIALLY DONE, some open findings
- [x] SSRF hardening including DNS-rebinding mitigation
  (`docs/ARCHITECTURE.md` §5).
- [x] XSS-relevant input handling (content treated as data, never
  executed).
- [x] Prompt-injection defenses, exercised against both a deterministic
  test provider and the real NVIDIA provider.
- [x] Concurrency-safe ingestion under real multi-threaded stress testing
  (`backend/tests/test_concurrency_race.py`,
  `test_concurrency_stress.py`).
- [x] Log secret redaction (`backend/app/core/logger.py`).
- [ ] Open findings tracked in `docs/RED_TEAM_REPORT.md` (as of this
  writing: CORS wildcard+credentials, NVIDIA-call hang investigation) —
  do not treat this phase as "done, no issues."
- [ ] Formal observability/metrics beyond application logging — `NOT
  IMPLEMENTED`.

## PHASE 8: Advanced Intelligence — NOT STARTED
- [ ] Conflict detection across contradictory sources.
- [ ] Automated entity resolution (tying "GPT-4" and "GPT4" to one
  canonical entity beyond case-insensitive string dedup).

This file will drift again if treated as the single source of truth —
`docs/ENGINEERING_STATUS.md` carries the up-to-date, evidence-cited
status; treat this roadmap as a coarse phase-level index into it.
