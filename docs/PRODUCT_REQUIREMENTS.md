# Product Requirements Document

## AI World Intelligence Platform

### 1. Product Overview
The AI World Intelligence Platform is an internal organizational application that continuously monitors the global AI ecosystem, detects meaningful developments, consolidates duplicate coverage into underlying events, enriches events with source-grounded AI analysis, preserves provenance, and presents the information through a fast, highly scannable web application.

The core goal is to answer:
- What changed in AI?
- What happened recently?
- Why does it matter?
- Which organizations/products/models are involved?
- Where is the original source?

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
- **Frontend**: Minimal, high-information-density dashboard. Card/tile layout. No unnecessary animations or UI clutter.
- **Event Detail**: Deep dive showing headline, summary, what changed, why it matters, sources, and provenance history.
- **Freshness**: ~20-minute SLA, with accurate tracking of "New Since Last Visit".

### 5. Administration & Security
- **Admin Panel**: Source management, ingestion health, manual event merges/splits, system metrics.
- **Security**: Strict XSS/SSRF protections. Untrusted input handling. Role-based access control (SSO/OIDC). No code execution from external sources.
