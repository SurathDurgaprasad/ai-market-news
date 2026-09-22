# Product Requirements Document

## AI World Intelligence Platform

Labels used below where current implementation diverges from the
original requirement: `CURRENT` (built), `PLANNED / FUTURE` (intentional,
not started), `NOT IMPLEMENTED` (required here but doesn't exist). See
`docs/ARCHITECTURE.md` for the implementation this document is checked
against.

### 1. Product Overview
The AI World Intelligence Platform is an internal organizational application that continuously monitors the global AI ecosystem, detects meaningful developments, consolidates duplicate coverage into underlying events, enriches events with source-grounded AI analysis, preserves provenance, and presents the information through a fast, highly scannable web application.

The core goal is to answer:
- What changed in AI?
- What happened recently?
- Which organizations/products/models are involved?
- Where is the original source?

Note: an earlier version of this section also listed "Why does it
matter?" as a core goal. That was superseded by a deliberate later
product decision to exclude editorial "why it matters" commentary
entirely — see `docs/ARCHITECTURE.md` §2 and §4. The system now answers
*what happened*, not *why it should matter to you*; the "why it matters"
generative content sits `NOT IMPLEMENTED` (intentionally, not by gap).

### 2. Core Principles
- **Intelligence System**: This is NOT a generic news reader, social network, chatbot, prediction engine, or rumor mill.
- **Source-of-Truth**: Every generated event must be traceable (EVENT → ARTICLE/DOCUMENT → SOURCE → ORIGINAL URL).
- **Event-Centric**: The core data object is an EVENT, not an ARTICLE. Multiple articles reporting the same thing constitute one event.
- **Importance Transparency**: Importance must not be a black-box. It must be explicit and inspectable (dimensions: novelty, impact, credibility).

### 3. Key Capabilities
- **Ingestion**: Robust ingestion from official APIs, RSS, GitHub, releases, and structured endpoints.
- **Deduplication**: Deterministic matching (URL, content hash) before LLM usage.
- **Clustering**: Grouping related articles into candidate events.
- **Source-Grounded Summarization**: AI summaries must be strictly based on source material. Unsupported claims are rejected. Conflicting claims are preserved and flagged.
- **Search & Filtering**: Metadata filtering (org, category, source tier, date, importance) and keyword search.

### 4. User Experience
- **Frontend**: Minimal, high-information-density dashboard. Card/tile layout. No unnecessary animations or UI clutter. `CURRENT`.
- **Event Detail**: Deep dive showing headline, summary, what changed, sources, and provenance history. `CURRENT` (no "why it matters" — see §1 note).
- **Freshness**: `PARTIALLY IMPLEMENTED` — polling intervals (10/20/60 min by source tier) target sub-hour freshness, not a firm ~20-minute SLA across all sources; "New Since Last Visit" tracking exists (`/api/v1/events/new_count`, `frontend/src/components/NewEventsNotifier.tsx`).

### 5. Administration & Security
- **Admin Panel**: `PARTIALLY IMPLEMENTED`. Source listing/health display exists (`frontend/src/app/admin/sources/page.tsx`); manual event merges/splits and system metrics are `NOT IMPLEMENTED`; the page's "Add Source"/"Edit" controls currently render without being wired to an action.
- **Security**: Strict XSS/SSRF protections and untrusted-input handling are `CURRENT` (see `docs/ARCHITECTURE.md` §5 and `docs/RED_TEAM_REPORT.md`). Role-based access control (SSO/OIDC) is `NOT IMPLEMENTED` — there is currently no authentication of any kind on the API or admin surface. No code execution from external sources: `CURRENT` (article content is always treated as untrusted data, never executed or interpreted as instructions).
