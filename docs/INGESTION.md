# Ingestion Pipeline

Describes the actual ingestion mechanism. Labels: `CURRENT`,
`PLANNED / FUTURE`, `NOT IMPLEMENTED`. See `docs/ARCHITECTURE.md` §2 for
the full pipeline stage list with source references — this document goes
one level deeper on the scheduling and fetch mechanics.

## Scheduling — `CURRENT`

No Celery, no cron. `backend/app/core/scheduler.py::IngestionScheduler`
wraps `apscheduler.schedulers.background.BackgroundScheduler`, started
in-process from the FastAPI app's `lifespan` handler
(`backend/app/main.py`) — it does not run under test (`is_test_runtime()`
guards both scheduler start/stop).

A 5-minute tick (`TICK_MINUTES`) evaluates every enabled `Source` and
runs the source if it's due, per `is_source_due()`:

| `polling_tier` | Interval |
|---|---|
| high | 10 min |
| medium | 20 min |
| low | 60 min |

A source in `health_status="failing"` gets exponential backoff on top of
its base interval (`base * 2^min(consecutive_failures, 4)`, capped at 4
hours) — a persistently broken feed is not hammered every tick.

Only `type == "rss"` sources are actually fetched
(`is_rss_source()` gate in `run_ingestion_cycle`) — `api`/`github`/`crawl`
source types are defined in the `Source` model as free-form strings but
have no fetcher implementation. See "Not implemented" below.

If the configured LLM provider is unavailable (`resolve_llm_mode() ==
LLM_UNAVAILABLE`), the entire cycle returns early with
`{"blocked": "llm_unavailable", ...}` before touching any source — the
system does not partially ingest with a broken/absent LLM.

## Fetch — `CURRENT`

`backend/app/core/fetcher.py::fetch_url`. SSRF-hardened (see
`docs/ARCHITECTURE.md` §5): DNS resolved once, rejected if any resolved
address is private/loopback/link-local/etc., then `socket.getaddrinfo` is
pinned per-thread so the eventual TCP connect cannot be redirected by a
second DNS lookup. Redirects are followed **manually** (`follow_redirects=False`
on the httpx client) so every hop gets the same SSRF check and DNS pin,
capped at 5 hops. Responses over 2MB are rejected. Retried with
exponential backoff on transient errors (429, 5xx, connection/timeout
errors) — bounded to 4 attempts.

## Parse — `CURRENT`

`backend/app/core/parser.py`. RSS/Atom via `feedparser`. HTML is stripped
from descriptions; malformed XML/one bad entry does not drop the whole
feed; entries are capped per feed to bound processing cost; enclosure/
media-thumbnail images are extracted when present.

## Normalize / dedup / classify / cluster / summarize / persist — `CURRENT`

Covered in full in `docs/ARCHITECTURE.md` §2 — not duplicated here to
avoid the two documents drifting apart again.

## Not implemented

- **GitHub / API / crawl source types** — `NOT IMPLEMENTED`. The `Source`
  model's `type` column accepts any string (comment lists
  `rss, github, api, crawl`), but `scheduler.py` only processes `rss`.
  Any source seeded with another type is silently skipped every tick
  (logged at info level: `"Skipping {name}, unsupported type {type}"`).
- **`robots.txt` compliance** — `NOT IMPLEMENTED`. Not checked before
  fetching.
- **Admin-triggered manual re-ingestion / merge / split** — `NOT
  IMPLEMENTED`. The admin sources page is read-only display; see
  `docs/ARCHITECTURE.md` §4.

## Planned / future

- Fetchers for `github` (releases/PRs) and generic `api` source types —
  `PLANNED / FUTURE`, not started.
- `robots.txt` respect for crawl-type sources, if/when that source type
  is implemented.
