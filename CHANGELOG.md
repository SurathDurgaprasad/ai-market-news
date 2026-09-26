# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-09-26

The first public version of AI Market News.

### Product

- Homepage for the current week: a trending strip by market area; "What's happening now" with one lead development and four secondary developments; the week's biggest developments; a dense latest feed with cards for significant developments and compact rows for the rest; an AI market pulse by area; and major AI players with total and substantive development counts (not a ranking).
- Event pages with headline, summary, image, what changed, verified quotes, the people and organizations involved, related developments, every supporting source, and update history.
- Player pages and a source-health page.
- Honest status: live, delayed, paused (no provider or provider unavailable) or unreachable, with pending-article counts.

### Intelligence

- Canonical events: one real-world development, with every article about it attached as evidence. Same-URL edits become versions only when the change is material.
- Deterministic deduplication (URL, content hash, guarded title match), then model relationship checks against at most five similar recent events.
- Model classification (kind, scope, security impact, market area, entities, importance), with importance calibrated from structured signals.
- Thirteen market areas; developments that fit none stay uncategorized.
- Source-grounded summaries in which every displayed quote is verified verbatim against the source.
- Newsletter digests read only their lead story.
- Providers: OpenAI (default), NVIDIA, Anthropic and Amazon Bedrock, behind one interface, with deadlines, bounded retries and fail-closed behaviour.

### Ingestion

- Curated registry of public RSS/Atom sources in four evidence tiers, managed with `manage_sources.py`.
- In-process scheduler with per-source polling tiers and exponential backoff.
- Articles are stored as pending during provider outages and retried automatically; exhausted quota is never retried.

### Security

- SSRF-hardened fetching: public addresses only, DNS pinning, per-hop redirect validation, decompression-safe size caps.
- Hostile-HTML handling, sanitized links, and a stored-URL-only image endpoint that serves re-encoded WebP.
- Prompt-injection boundaries, secret redaction in logs, and a credential-free test suite; live-provider tests are opt-in.

### Operations

- Usage ledger for every provider request (tokens, latency, success; never prompts or keys) and `manage_sources.py llm-usage`.
- Maintenance jobs that estimate first, run as dry runs, apply separately and can be reverted.
- Resized, cached event images (192/640/1200 px WebP).
- `SCHEDULER_ENABLED=0` serves stored data without ingestion.
- CI for backend tests, frontend tests, typecheck, lint, production build and the backend Docker image.

[0.1.0]: https://github.com/SurathDurgaprasad/AI-Market-News/releases/tag/v0.1.0
