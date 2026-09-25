# Sources

Sources are rows in the `source` table. Adding, disabling or changing one is a data change: no code, parser or migration is needed, and the running scheduler picks it up on its next 5-minute tick.

## The curated registry

`backend/sources.registry.json` lists the curated public feeds (official lab blogs, research, news and community). Load or refresh them with:

```bash
cd backend
python seed_sources.py
```

Re-seeding updates a changed URL in place and never re-enables a source you disabled.

Each entry:

```json
{
  "organization": "Example Lab",
  "name": "Example Lab Blog",
  "url": "https://example.com/blog/rss.xml",
  "tier": "primary",
  "polling_tier": "high",
  "enabled": true
}
```

## Tiers

The tier says what kind of evidence a source is, and it is shown to readers:

| `tier` | Shown as | Examples |
|---|---|---|
| `primary` | Official source | A lab's or company's own blog |
| `research` | Research paper | Paper and preprint feeds |
| `secondary` | News coverage | Technology publications |
| `community` | Discussion | Aggregators and forums |

Primary and research items are always in scope for the feed. Secondary and community items must read as AI developments, and community posts outside AI scope are dropped before any model call.

When a community link points at an original article (for example a news story shared on a forum), the original publisher is shown, labelled "Original article", never "Official source".

## Commands

From `backend/`:

```bash
python manage_sources.py list
python manage_sources.py add --organization "Example Lab" --name "Example Lab Blog" \
    --url "https://example.com/blog/rss.xml" --tier primary --polling-tier high
python manage_sources.py disable --name "Example Lab Blog"
python manage_sources.py enable  --name "Example Lab Blog"
python manage_sources.py update  --name "Example Lab Blog" --url "https://example.com/new-feed.xml"
python manage_sources.py ingest          # run one cycle now
```

- `add` with an existing organization and name updates that row.
- `update --url` clears the old URL's failure history, so the new feed is fetched on the next tick.
- The URL must be a public `http(s)` address; `javascript:`, `file:` and loopback or private hosts are rejected.

## Health

`GET /api/v1/sources/` and the **Sources** page show each source's health:

| Status | Meaning |
|---|---|
| `healthy` | Last fetch succeeded |
| `degraded` | Fetched, but new articles are stored and waiting for the language model |
| `failing` | The fetch failed; retried with exponential backoff (up to 4 hours) |
| `disabled` | Not fetched |

The last result is summarized in words, for example "20 in feed · nothing new · 20 already known" or "30 in feed · 2 new · 19 out of scope". A URL that serves an HTML page instead of a feed is reported as failing, not silently healthy.

## Disabled curated feeds

Some curated organizations are in the registry but disabled, because no public feed could be fetched: the feed returned 404, served HTML instead of RSS, blocked automated clients, or rate-limited every request. Re-enable one only after `update --url` points it at a feed that validates.
