# Source registry

Sources are rows in SQLite. The scheduler loads every enabled RSS row on each tick. Adding a source does not require a code change, a new parser, or a migration.

Curated feeds live in `backend/sources.registry.json`. `python seed_sources.py` inserts them and updates a changed URL in place. It does not turn a disabled source back on.

## Add a source

From `backend/`:

```powershell
python manage_sources.py add --organization "OpenAI" --name "OpenAI Research" --url "https://example.com/feed.xml" --tier research --polling-tier medium
python manage_sources.py ingest
```

Tiers: `primary`, `research`, `secondary`, `community`.
Polling: `high` (10 min), `medium` (20 min), `low` (60 min).

The running API also notices the new row on its next 5-minute tick. No restart is required for the scheduler to see it. A disabled source is skipped:

```powershell
python manage_sources.py disable --name "OpenAI Research"
python manage_sources.py enable --name "OpenAI Research"
python manage_sources.py update --name "OpenAI Research" --url "https://example.com/new.xml"
python manage_sources.py list
```

Only `type=rss` is fetched. The URL must be a public `http` or `https` address. `javascript:`, `file:`, and loopback hosts are rejected. A feed that returns an error is marked `failing` and retried with backoff. Other sources in the same cycle continue.

Repeated adds with the same organization and name update the existing row.

## What the feed does with them

Primary and research sources are in scope for the week feed. Secondary and community items must read as AI developments. Conference-pass promotions are dropped. A bare mention of a GPU is not enough for a community post.

## Disabled curated feeds (checked 2026-09-24)

These are disabled in `sources.registry.json` because no public feed could
be fetched. Alternate paths were probed with the production fetcher, and
none returned a valid RSS/Atom feed. Re-enable one only after
`manage_sources.py update --url ...` points it at a feed that validates.

| Source | Result |
|---|---|
| Anthropic News | 404; no feed at `/rss.xml` or `/news/feed` |
| DeepSeek Blog | 404; docs-site paths return HTML, not a feed |
| Cohere Blog | HTML instead of a feed; `/rss.xml` and `/blog/feed` 404 |
| Stability AI Blog | 404; Squarespace `?format=rss` returns no feed |
| xAI Blog | 403/404 (automated clients blocked) |
| Perplexity Blog | 403 (automated clients blocked) |
| VentureBeat AI | rate-limited on every attempt (429 retries exhausted) |

Meta AI Research moved to Meta's engineering blog AI Research feed,
`https://engineering.fb.com/category/ai-research/feed/`, which validates.
