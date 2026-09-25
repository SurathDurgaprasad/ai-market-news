# Ingestion

Ingestion turns feed entries into canonical events. It runs inside the API process (`backend/app/core/scheduler.py`) and processes one article at a time through `IntelligencePipeline.process_article` (`backend/app/core/pipeline.py`).

## Scheduling

A 5-minute tick checks every enabled source and fetches the ones that are due:

| `polling_tier` | Interval |
|---|---|
| `high` | 10 minutes |
| `medium` | 20 minutes |
| `low` | 60 minutes |

A failing source backs off exponentially (`interval × 2^failures`, at most 4 hours), so a broken feed is not requested every tick. Other sources in the same cycle continue. Only `rss` sources (RSS and Atom) are fetched.

`python manage_sources.py ingest` runs one cycle immediately. `SCHEDULER_ENABLED=0` turns scheduling off.

## When the language model is unavailable

Fetching and enrichment are separate, so a provider outage does not lose articles:

- **Not configured** (no key, SDK missing): the cycle is blocked before any fetch, and `/api/health` reports `llm_mode: unavailable`.
- **Outage during a cycle** (timeout, 5xx, rate limit, exhausted quota): the article is stored with `enrichment_status = pending` and a redacted error. The provider is not called again for 15 minutes; sources keep being fetched and new articles stored as pending. The homepage says enrichment is paused and how many articles are waiting.
- **Recovery**: each cycle first retries up to 20 pending articles, oldest first, in place. No event is ever created without the model, and no fake content is substituted.

A source whose fetch succeeded is never marked failing because of the provider; it shows as `degraded`, with the number of articles awaiting enrichment.

## Per-article stages

1. **Normalize.** Canonicalize the URL; reject anything without a safe public `http(s)` URL and a title.
2. **Noise filter.** Obvious clickbait patterns are rejected before any model call. Community-tier (aggregator) stories outside AI scope are rejected too, using the same rule as the week feed. Rejected articles are remembered and never re-processed.
3. **Extract.** When a feed only has a snippet, the article page is fetched through the SSRF-guarded fetcher and its main body extracted. Post-body containers are preferred over the whole page, and markup is stripped in linear time without turning `data-*` JSON into text.
4. **Deterministic deduplication.**
   - **Same URL:** a known URL is re-checked for edits only within 7 days. A change becomes a new *version* of the event only when it is material: counters, relative times and removed page chrome are not.
   - **Same content hash:** syndicated copies attach to the existing event.
   - **Guarded title match:** high word overlap plus a shared distinctive marker (version, product code, amount) and no conflicting one, so "raises $6.6B" never merges with "raises $6.6M".
5. **Classify** (1 model request). Kind, scope, security impact, market area, entities and an importance score. The score is calibrated into the band the structured signals allow; see [intelligence.md](intelligence.md).
6. **Relationship analysis** (at most 5 model requests). Candidates are recent events with overlapping entities and a compatible kind, the most similar first. The model answers `SAME_EVENT`, `UPDATE_TO_SAME_EVENT`, `RELATED_EVENT` or `DIFFERENT_EVENT`, and only `SAME_EVENT` merges. A merged article becomes supporting coverage of the existing event.
7. **Summarize** (1 model request). Headline, summary, what changed and up to three quotes.
8. **Verify evidence.** Each quote must be found verbatim in the source text, or it is dropped. If none survive, 1–2 real source sentences overlapping the summary are used instead, and they are verified the same way.
9. **Persist.** Event, article and link are written in one transaction, retried on SQLite lock contention.

Newsletter digests (one URL, a lead story plus a link roundup, such as MIT Technology Review's "The Download") are cut to their lead story for every model call, so a card never takes its headline from one story and its entities from another. The stored article keeps the full text.

After each cycle, `consolidate_safe_duplicates` merges live events from the last 14 days that the headline rules identify as the same development.

## Fetching

`backend/app/core/fetcher.py` is the only way the backend fetches a URL:

- Public `http`/`https` only; private, loopback, link-local, reserved and metadata addresses are rejected.
- DNS is resolved once and the connection pinned to the validated addresses, closing DNS-rebinding gaps.
- Redirects are followed manually (at most 5), each hop re-validated and re-pinned.
- Bodies are streamed with a cap on the decompressed size (2 MB for pages, 8 MB for images), so a small compressed response cannot expand in memory.
- Transient errors (429, 5xx, timeouts) are retried with exponential backoff, up to 4 attempts.

## Parsing

`backend/app/core/parser.py` parses RSS and Atom with `feedparser`. One malformed entry does not drop the feed, entries per feed are capped, and enclosure or media thumbnails are captured as the image candidate.

## Maintenance commands

These repair or improve stored data. Each is a dry run by default and prints what it would change:

| Command | Purpose | Model requests |
|---|---|---|
| `repair-headlines [--apply]` | Restore a confidently known organization in placeholder headlines | none |
| `repair-versions [--refetch] [--apply]` | Undo versions created only by page counters or chrome | none |
| `recheck-duplicates [--max-checks N] [--apply]` | Ask the relationship model about recent events ingestion never compared | up to `--max-checks` |
| `repair-digests [--apply]` | Reclassify digest events whose entities came from the roundup | 1 per affected event |
| `rebuild-digest-card --event ID --run FILE` / `--apply FILE` | Rebuild a digest event whose headline came from the roundup | 2 |
| `backfill-categories` / `--run FILE` / `--apply FILE` / `--revert` | Categorize older events; see [intelligence.md](intelligence.md#category-backfill) | about 2 per 20 events |

## Not supported

- Source types other than RSS/Atom (the `type` column accepts other values, but they are skipped).
- `robots.txt` checks: only feed URLs and the article pages they link to are fetched.
- Manual merge or split from the web UI (the sources page is read-only).
