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

Fetch/parse and LLM enrichment are separate stages. If the configured
provider fails *during* a cycle (timeout, outage):

- The article being processed is stored as an `article` row with
  `enrichment_status = "pending"` and a redacted `enrichment_error`. No
  event is created: nothing semantic exists without the LLM.
- The provider is not called again for `PROVIDER_OUTAGE_COOLDOWN`
  (15 minutes). The rest of the cycle, and later cycles inside the
  cooldown, keep fetching every due source in store-only mode.
- A source whose fetch succeeded is never marked failing for this. It is
  `degraded` with "N article(s) stored, awaiting enrichment", and its
  normal polling interval applies.
- When the cooldown has passed, each cycle first retries up to
  `PENDING_RETRY_LIMIT` (20) pending articles, oldest first, in place on
  the same row, then processes new articles. A retried article that
  enrichment rejects is marked `rejected` and not retried again.
- `article.url` is unique, and a re-fetched pending URL is recognized, so
  repeated outage cycles never create a second row.

An unconfigured provider (no key) is a configuration error, not an
outage: the cycle stays blocked before fetching, as above.

Same-URL updates: a re-fetched article whose text changed creates a new
event version only when the change is material. Counters and relative
times ("Upvote 72", "+66", "3 days ago", `"followerCount": 4172`,
related-post cards "19 August 17") and Unicode width variants are
immaterial (`is_immaterial_change`); any other changed word or figure is
material. The new text is compared with every stored version of the URL.
Without this, feeds whose pages carry live counters (the Hugging Face
blog) were re-summarized on every poll, which filled whole cycles with
LLM calls and produced no new developments.

Text only removed between versions (page chrome that a cleaner extraction
no longer includes) is also immaterial; added or replaced words are not.

Fetches reuse one verifying TLS context (`fetcher.tls_context()`); httpx
otherwise re-reads the CA bundle for every request.

Article pages: `_prefer_main_html` takes a recognised post-body container
(`blog-content`, `post-content`, `article-body`, `entry-content`, ...)
before `<article>`/`<main>`, and `sanitize_html` strips tags in linear
time while honouring quoted attribute values, so JSON in `data-*`
attributes never becomes article text.

Semantic merge: an incoming article is compared by the LLM only with the
`MAX_RELATIONSHIP_CHECKS` (5) most similar recent events, ranked by shared
content words and entities. Previously one article that shared only
"OpenAI" with many events could make 22 sequential relationship calls.

Avoided LLM work:
- A known article is re-fetched for edits only within 7 days of first
  being stored (`UPDATE_RECHECK_WINDOW`); older known URLs are duplicates
  without a page download.
- Community-tier (general-tech aggregator) stories outside AI scope are
  rejected before any LLM call, using the same rule the week feed applies.
- Rejected articles are stored with `enrichment_status = "rejected"` and
  skipped on later polls before any fetch or LLM call.

Changing a source URL (`manage_sources.py update --url`, or a curated URL
change on re-seed) clears the old URL's failure history so the new feed
is fetched on the next tick instead of after backoff.

Data repairs (dry run by default, reversible):
`manage_sources.py repair-versions` restores the first-recorded time on
versions created only by page counters; `--refetch` also compares version 1
with the live page under today's extractor, which catches versions created
by page chrome (Microsoft Research's rotating `msr-promo` block, Hugging
Face comment JSON). Only versions not marked as churn are shown as
"Updated" in the UI (`is_update`). `repair-headlines` restores a
confidently known organization in placeholder headlines.
`recheck-duplicates` asks the configured relationship model about recent
live cards that ingestion never compared (same filters as ingestion:
within 48 hours, overlapping entities, compatible kinds, most similar
first) and merges only SAME_EVENT pairs. It compares the two cards, not
raw article text, so a newsletter roundup does not match every story it
mentions.

Promotional blocks (`class` containing a `promo` token, with nested divs)
are removed by `sanitize_html`, so feed bodies and fetched pages both lose
them before hashing and change detection.
`GET /events/overview` reports `pending_enrichment` and
`enrichment_paused`; `/api/health` reports `enrichment_paused`.

After the sources, `consolidate_safe_duplicates` merges live events the
headline predicates treat as one development. It compares only events
from the last 14 days (`CONSOLIDATION_WINDOW`), because pairwise
comparison is quadratic and older canonical events are already settled.

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
