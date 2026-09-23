> Historical product-discovery notes. The running system is FastAPI + SQLite + APScheduler + Next.js, described in `README.md` and `docs/ARCHITECTURE.md`. Recommendations below that mention PostgreSQL, pgvector, Redis, or BullMQ were not built.

# AI World Intelligence Platform — End-to-End Product Discovery

**Research Report | September 2026**

> **Note on evidence:** This report synthesizes findings from official documentation, repositories, product pages, and technical references available as of September 2026. Facts, analysis, and recommendations are distinguished throughout. Where information is uncertain or unavailable, this is stated explicitly.

---

## A. Executive Summary

**What should be built and why.**

Build a hosted internal web application that continuously monitors a curated registry of AI-ecosystem sources, converts raw articles and releases into deduplicated events, enriches them with AI-generated summaries that preserve source provenance, and exposes them through a scannable card/tile feed with search, filtering, and an auditable event history.

The core rationale:

1. **The AI ecosystem publishes too fast for manual monitoring.** A single week can produce dozens of model releases, framework updates, funding rounds, regulation changes, and developer-tool changes across dozens of organizations. RSS readers alone do not solve the "same event, many sources" problem — they produce noise, not signal.
2. **Provenance is the product's differentiator.** An internal intelligence tool must answer "where did this come from?" and distinguish primary (official) from secondary (third-party) and community (developer discussion) sources. Generic aggregators do not enforce this distinction.
3. **Event-level intelligence, not article-level aggregation.** The system must cluster multiple reports of the same underlying event into one canonical event card with a primary source and supporting secondary sources.
4. **The 20-minute cadence is a user-experience goal, not a per-source polling mandate.** Research shows that tiered polling schedules (15 min / 60 min / 6 hours based on observed update frequency) are more scalable and less likely to trigger rate limits than naive uniform polling.
5. **Scope must be disciplined.** The system should monitor a finite, curated source registry — not "everything on the internet." V1 should cover foundation-model labs, major AI developer tools, open-weight model hubs, and selected news/community sources.

**Recommended V1 architecture in one sentence:** RSS/API-first ingestion with tiered scheduling → deterministic deduplication and entity extraction → embedding-based clustering → LLM enrichment at the event level with citation anchoring → PostgreSQL + pgvector storage → Next.js card-feed frontend with hybrid search.

---

## B. Problem Definition

**The exact problem being solved.**

Engineers, engineering managers, and technical leads need to understand what is happening across the AI ecosystem in order to make informed decisions about tooling, architecture, vendor selection, and team priorities. Today this awareness is assembled manually from bookmarks, newsletters, Slack forwards, and ad-hoc browsing — which is inconsistent, non-auditable, and does not scale.

The specific problem:

- **Information is fragmented.** Official announcements, research papers, GitHub releases, developer discussions, and news coverage live in different places with different update cadences.
- **Duplication dominates.** A single model release may generate 10–50 articles across news sites, blogs, and social platforms. A human reader cannot distinguish "new information" from "the same information reported again."
- **Provenance is lost.** When information is forwarded or summarized, the original source is often lost. This makes it impossible to verify whether a claim originated from the company itself or from a third-party report or rumor.
- **Importance is unclear.** Not every release or announcement matters equally. A critical security patch, a new model family, and a minor documentation update all arrive through the same channels.
- **History is not preserved.** Once a story scrolls past, there is no structured way to revisit it or understand how it evolved.

The product exists to solve these five problems for an internal organizational audience.

---

## C. Product Definition

**What the product is:**

- An internal web application that monitors a curated source registry.
- An event-level intelligence feed, not a raw article aggregator.
- A provenance-preserving system that clearly distinguishes primary, secondary, and community sources.
- A searchable, filterable historical archive of AI-ecosystem developments.
- A tool designed for engineers and engineering managers, not the general public.

**What the product is not:**

- Not a real-time social media monitoring tool.
- Not a replacement for official documentation or release notes.
- Not a general-purpose news reader.
- Not a public-facing news website.
- Not a system that claims to "predict" or "recommend" — it surfaces and organizes information.

---

## D. Users

| User Type | Primary Needs | Key Questions |
|---|---|---|
| Software Engineer | Stay current with tools, frameworks, and model APIs relevant to their stack | "Did any tool I use release an update? Are there new open-weight models I can use locally?" |
| Senior Engineer / Tech Lead | Assess technical significance, identify risks and opportunities | "What changed in the ecosystem that affects our architecture decisions?" |
| Engineering Manager | Understand landscape for team planning and vendor evaluation | "What are the major developments I should be aware of this week? What needs escalation?" |
| Technical Architect | Track standards, protocols, infrastructure, and platform shifts | "Are there new protocols (e.g., MCP), infrastructure patterns, or standards emerging?" |

**User stories (representative):**

- As an engineer, I want to open the homepage and immediately see what changed since my last visit, so I do not need to remember what I already read.
- As a tech lead, I want to filter events by category (e.g., "Open Source," "Coding") and by organization (e.g., "Anthropic") so I can focus on my team's dependencies.
- As a manager, I want to see a concise event summary with a clear indication of whether the source is official or secondary, so I can trust the information.
- As any user, I want to click through to the original source to verify details.

---

## E. Functional Requirements

### E1. Source Registry

- **E1.1** The system must maintain a registry of sources, each with: source name, type (RSS, API, GitHub, crawl, etc.), URL, update cadence, trust tier, category tags, and enabled/disabled status.
- **E1.2** The registry must support hierarchical trust tiers: **Primary** (official company/lab), **Secondary** (credible news/analyst), **Community** (developer discussion, social).
- **E1.3** Source health must be tracked (last successful fetch, last error, consecutive failures).
- **E1.4** Sources must be classifiable by polling tier (high / medium / low frequency).

### E2. Ingestion

- **E2.1** The system must fetch from RSS/Atom feeds, GitHub Releases API, and selected JSON/REST APIs.
- **E2.2** The system must support conditional GET (`If-None-Match`, `If-Modified-Since`) to minimize bandwidth and respect server resources.
- **E2.3** The system must implement exponential backoff on 429 and 5xx responses.
- **E2.4** The system must support WebSub (PubSubHubbub) for feeds that advertise it, allowing push-based updates.
- **E2.5** The system must store raw fetched content (or a hash and excerpt) for provenance and re-processing.

### E3. Deduplication & Event Detection

- **E3.1** The system must perform near-duplicate detection using deterministic methods (MinHash LSH, SimHash, or title Jaccard similarity) before any LLM processing.
- **E3.2** The system must cluster semantically similar articles into candidate events using embedding-based clustering (e.g., HDBSCAN).
- **E3.3** The system must identify a canonical primary source for each event when one exists (e.g., the organization's official blog post).
- **E3.4** The system must version events: updates to an existing event should create a new version, not a new event.
- **E3.5** The system must support manual merging and splitting of events by administrators.

### E4. Enrichment

- **E4.1** Each event must be classified into one or more categories from a controlled taxonomy.
- **E4.2** Each event must be assigned an importance score based on a defined rubric (not a single opaque number).
- **E4.3** Each event must receive an AI-generated summary that includes: headline, short summary, "what changed," and "why it matters."
- **E4.4** All AI-generated content must be source-grounded with citations to specific source documents.
- **E4.5** The system must extract and link entities: organizations, products, models, people, technologies.

### E5. Storage & Search

- **E5.1** The system must store events, articles, sources, entities, and provenance links in a relational database.
- **E5.2** The system must support full-text search across event summaries and article titles.
- **E5.3** The system must support semantic (vector) search for related events and similarity queries.
- **E5.4** The system must support filtering by: date range, category, organization, source type, source tier, and importance.
- **E5.5** The system must preserve historical versions of events and articles.

### E6. Frontend

- **E6.1** The homepage must display a card/tile feed of events, sorted by most recent or by importance.
- **E6.2** Each card must display: headline, one-line summary, category tags, organization tags, source tier indicator (primary/secondary/community), publication/detection time, and a link to the event detail page.
- **E6.3** The system must indicate "new since last visit" for returning users.
- **E6.4** The event detail page must display: full summary, "what changed," "why it matters," list of sources with links, entity associations, and related events.
- **E6.5** The system must support keyword search and the filters listed in E5.4.
- **E6.6** The system must support dark/light mode and keyboard navigation.

### E7. Administration

- **E7.1** Administrators must be able to add, edit, disable, and delete sources.
- **E7.2** Administrators must be able to view source health, ingestion job status, and system metrics.
- **E7.3** Administrators must be able to manually merge/split events and correct classifications.
- **E7.4** The system must log administrative actions in an audit log.

---

## F. Non-Functional Requirements

| Requirement | Target | Notes |
|---|---|---|
| **Freshness** | New events visible within 20 minutes of source publication for high-frequency sources; within 1 hour for medium-frequency | Not all sources polled every 20 min — see §E2 and §5 |
| **Ingestion reliability** | >99% successful fetch rate for healthy sources | Measured over 7-day windows |
| **Event deduplication** | <5% false-positive merge rate; <2% missed duplicate rate | Validated against a human-labeled test set |
| **Summary factuality** | >95% of summary claims supported by at least one cited source | Measured by human evaluation and automated attribution checks |
| **Availability** | 99.5% uptime during business hours (target) | Internal tool — 24/7 availability not required for V1 |
| **Search latency** | <500ms for keyword search; <1s for semantic search | p95 |
| **Page load** | <2s for homepage feed (p95) | |
| **Security** | SSO required; all API keys encrypted at rest; ingested content treated as untrusted | See §N |
| **Auditability** | Every event retains full provenance chain: event → articles → sources | |
| **Scalability** | Support 100–10,000 events/month without architecture changes | See §O |

---

## G. Source Strategy

### G1. Source Hierarchy

| Tier | Definition | Examples | Trust Treatment |
|---|---|---|---|
| **Primary** | The organization itself announced or released something | Official blogs, GitHub releases, model cards, documentation changelogs, official social accounts | Highest trust; treated as canonical source |
| **Secondary** | Credible third party reported or analyzed | Reuters, Bloomberg, FT, TechCrunch, The Verge, Ars Technica, MIT Tech Review, VentureBeat | Medium trust; used for context and corroboration; clearly labeled |
| **Community** | Developers/users discussed or speculated | Hacker News, Reddit, X, developer forums, personal blogs | Lowest trust; used for signal detection; never presented as fact without primary/secondary corroboration |

> **Important:** Community sources can surface early signals (e.g., a GitHub commit that reveals a pending release), but the system must not present community discussion as confirmed fact. Rumors, leaks, and speculation must be labeled as such.

### G2. Recommended Initial Source Registry (V1)

**Primary — Foundation Model Labs & Major AI Companies**

| Organization | Recommended Source Type | Notes |
|---|---|---|
| OpenAI | RSS: `openai.com/news/rss.xml`; GitHub releases; developer blog | |
| Anthropic | RSS (generated via community feeds if no native feed); GitHub releases | |
| Google DeepMind | RSS: `deepmind.google/blog/feed/basic/` or `/blog/rss.xml` | |
| Meta AI | RSS: `about.fb.com/news/feed/`; `ai.meta.com/blog/` | |
| Hugging Face | Blog RSS; model repository updates via Hub API | |
| NVIDIA | Developer blog RSS; newsroom RSS | |
| Microsoft | AI blog RSS; Azure AI blog RSS | |
| AWS | ML blog RSS: `aws.amazon.com/blogs/ai/feed`; SageMaker/Bedrock feeds | |
| Mistral AI | Official blog / news page; GitHub releases | |
| Cohere | Official blog / news page; GitHub releases | |
| xAI | Official blog / news page | |
| Moonshot AI | Official site; GitHub | |
| Qwen / Alibaba | GitHub releases; official blog | |
| DeepSeek | GitHub releases; official site | |
| ByteDance | Official announcements; GitHub | |
| Tencent | Official announcements; GitHub | |
| Baidu | Official announcements; GitHub | |
| Zhipu AI | GitHub; official announcements | |
| MiniMax | GitHub; official announcements | |
| AI21 Labs | Official blog; GitHub | |
| Stability AI | Official blog; GitHub | |
| Runway | Official blog | |
| Midjourney | Official announcements (Discord/web) | |
| ElevenLabs | Official blog | |
| Perplexity | Official blog | |
| Apple | ML research blog; newsroom | |

**Primary — AI Developer Ecosystem**

| Organization / Project | Source Type | Notes |
|---|---|---|
| Cursor | Official blog / changelog | |
| Windsurf (Devin Desktop) | Official blog / changelog | |
| Cline | GitHub releases; official blog | |
| OpenCode | GitHub releases; official docs | |
| LangChain | GitHub releases (LangGraph, LangChain) | |
| CrewAI | GitHub releases | |
| OpenHands | GitHub releases | |
| MCP ecosystem | GitHub (modelcontextprotocol org); specification releases | |
| NVIDIA developer ecosystem | Developer blog RSS | |
| Major open-source AI GitHub projects | GitHub Releases API + Trending API | |

**Research & Papers**

| Source | Type | Notes |
|---|---|---|
| arXiv cs.AI, cs.CL, cs.LG | RSS: `rss.arxiv.org/rss/cs.AI` | High volume; requires filtering |
| Hugging Face Daily Papers | RSS / web scrape | Curated subset of arXiv |

**Secondary / News**

| Source | Type | Notes |
|---|---|---|
| TechCrunch AI | RSS | |
| The Verge AI | RSS | |
| Ars Technica | RSS | |
| MIT Technology Review AI | RSS | |
| VentureBeat AI | RSS | |
| Reuters Technology | RSS | |
| Bloomberg Technology | RSS (limited) | |
| Financial Times Tech | RSS (limited) | |
| AP News Technology | RSS | |

**Community**

| Source | Type | Notes |
|---|---|---|
| Hacker News | API (`hn.algolia.com/api/v1`) | Signal detection only; high noise |
| Reddit (r/MachineLearning, r/LocalLLaMA) | API (with rate limits) | Signal detection only |
| X / Twitter (selected accounts) | API (cost/access constraints) | Signal detection only |

**Policy / Regulation**

| Source | Type | Notes |
|---|---|---|
| Digital Policy Alert | RSS / newsletter | |
| Alston & Bird AI Quarterly | Publication | |
| Clifford Chance Tech Policy Unit | Publication | |

### G3. Source Discovery

New sources should be discovered through:

- **Cross-referencing:** When an event's secondary sources cite a primary source not yet in the registry, that source should be flagged for review.
- **GitHub organization scanning:** Monitor the GitHub organizations of known AI companies for new repositories and releases.
- **Community suggestions:** Administrators can add sources manually based on team input.
- **Automated feed validation:** New feed URLs must pass a health check (HTTP 200, valid XML/JSON) before being enabled.

### G4. Source Health

Each source must track:

- Last successful fetch timestamp
- Last error timestamp and message
- Consecutive failure count
- Average response time
- Update frequency (rolling 7-day)
- Health status: **Healthy** / **Degraded** / **Failing** / **Disabled**

Sources that fail 3 consecutive fetches should be automatically degraded. Sources that fail 5 consecutive fetches should be flagged for administrator review.

---

## H. Event Intelligence Pipeline

### H1. Pipeline Stages

```text
[Source] → Fetch → Normalize → Deduplicate → Extract → Cluster → Classify → Summarize → Store → Index
```

| Stage | Input | Output | Primary Technique |
|---|---|---|---|
| **Fetch** | Source URL | Raw HTTP response | Conditional GET, exponential backoff |
| **Normalize** | Raw response | Structured article record (title, body, URL, pub date, source) | Feed parser (feedparser / gofeed) |
| **Deduplicate** | Article record | Deduplicated article or "duplicate of X" | MinHash LSH, SimHash, or Jaccard title similarity |
| **Extract** | Article text | Entities (orgs, products, models, people), claims | NER (spaCy), LLM structured extraction |
| **Cluster** | New article + recent articles | Candidate event assignment | Embedding similarity + HDBSCAN |
| **Classify** | Event + articles | Category labels, importance score | Rules + LLM classification |
| **Summarize** | Event cluster | Headline, summary, what changed, why it matters | LLM with citation anchoring |
| **Store** | Enriched event | Database records | PostgreSQL + pgvector |
| **Index** | Stored event | Search index | PostgreSQL FTS / pgvector |

### H2. Deduplication Strategy

**Deterministic first, LLM later.**

1. **Exact URL match:** If the URL has already been ingested, skip.
2. **Title Jaccard similarity > 0.80:** Reject as duplicate.
3. **MinHash LSH (85% similarity threshold):** Near-duplicate detection.
4. **Embedding cosine similarity > 0.92:** Flag as candidate duplicate for human review or LLM-assisted decision.

Only articles that pass all deterministic checks should be sent to embedding-based clustering.

### H3. Event Clustering

**Candidate event formation:**

- New articles are embedded using a small embedding model (e.g., `text-embedding-3-small` at $0.02/M tokens).
- The new article's embedding is compared against all articles published within the last 7 days (rolling window).
- If cosine similarity to an existing cluster's centroid exceeds a threshold (tunable, initially 0.75), the article is assigned to that cluster.
- If no cluster matches, a new candidate event is created.

**Cluster maintenance:**

- HDBSCAN is used to re-cluster the rolling window periodically (e.g., every hour) to detect clusters that should be merged or split.
- Clusters with fewer than 2 articles after 24 hours are considered "unconfirmed events" and may be down-ranked.
- Clusters containing a primary source are promoted to "confirmed events."

### H4. Deterministic vs. LLM Processing

| Task | Recommended Technique | Rationale |
|---|---|---|
| URL deduplication | Deterministic | Exact match |
| Near-duplicate detection | Deterministic (MinHash/SimHash) | Fast, no API cost, auditable |
| Entity extraction | Deterministic NER (spaCy) + LLM fallback | NER is fast and reliable for known entities; LLM handles novel entities |
| Event clustering | Deterministic (embedding + HDBSCAN) | No LLM cost; tunable thresholds |
| Category classification | LLM with structured output | Requires semantic understanding |
| Importance scoring | Hybrid (rules + LLM) | Rules for obvious cases (e.g., primary source from major lab); LLM for nuanced assessment |
| Summarization | LLM with citation anchoring | Requires synthesis across sources |
| Conflict detection | LLM | Requires detecting contradictions across sources |

> **Verification note:** The specific similarity thresholds (0.75, 0.80, 0.85, 0.92) are starting points for tuning, not validated optimal values. They must be calibrated against a human-labeled evaluation set before production.

---

## I. Data Model

### I1. Conceptual Entities

| Entity | Description | Key Attributes |
|---|---|---|
| **Organization** | A company, lab, or institution | `id`, `name`, `aliases[]`, `website`, `type` (company/lab/standards-body) |
| **Product** | A product or service | `id`, `name`, `organization_id`, `type` (model/IDE/framework) |
| **Model** | A specific AI model | `id`, `name`, `family`, `organization_id`, `license`, `release_date` |
| **Project** | An open-source project | `id`, `name`, `organization_id`, `github_url`, `license` |
| **Source** | A monitored source (feed, API, account) | `id`, `name`, `type`, `url`, `tier` (primary/secondary/community), `polling_tier`, `enabled`, `health_status`, `last_fetch_at` |
| **Article** | A fetched document | `id`, `source_id`, `title`, `url`, `published_at`, `fetched_at`, `content_hash`, `body_excerpt`, `raw_content_ref` |
| **Event** | A canonical intelligence event | `id`, `title`, `summary`, `what_changed`, `why_it_matters`, `primary_source_article_id`, `category`, `importance_score`, `confidence`, `first_detected_at`, `last_updated_at`, `version` |
| **EventCluster** | Association between event and articles | `event_id`, `article_id`, `is_primary`, `similarity_score`, `added_at` |
| **Claim** | A atomic factual claim extracted from a source | `id`, `event_id`, `article_id`, `claim_text`, `supporting_span`, `extracted_at` |
| **Entity** | An extracted named entity | `id`, `name`, `type` (org/product/model/person/tech), `canonical_id` |
| **EventEntity** | Association between event and entity | `event_id`, `entity_id`, `role` (subject/mentioned) |
| **Category** | A controlled taxonomy category | `id`, `name`, `parent_id`, `description` |
| **Tag** | A free-form or controlled tag | `id`, `name`, `type` |
| **EventTag** | Association between event and tag | `event_id`, `tag_id` |
| **User** | An internal user | `id`, `email`, `display_name`, `role`, `preferences` |
| **SavedItem** | A user-saved event | `user_id`, `event_id`, `saved_at`, `notes` |
| **SourceHealth** | Time-series health data for a source | `source_id`, `timestamp`, `status`, `response_time_ms`, `error_message` |
| **IngestionJob** | A record of an ingestion run | `id`, `source_id`, `started_at`, `completed_at`, `status`, `items_fetched`, `items_new`, `error` |
| **ProcessingResult** | Record of an LLM processing call | `id`, `event_id`, `model`, `prompt_type`, `input_tokens`, `output_tokens`, `cost`, `latency_ms`, `status` |
| **Correction** | A manual correction by an admin | `id`, `event_id`, `correction_type`, `old_value`, `new_value`, `corrected_by`, `corrected_at` |
| **AuditLog** | Administrative action log | `id`, `user_id`, `action`, `entity_type`, `entity_id`, `timestamp`, `details` |

### I2. Key Relationships

- **Organization** 1—N **Product**, **Model**, **Project**
- **Source** 1—N **Article**
- **Article** 1—N **EventCluster** N—1 **Event**
- **Event** N—N **Entity** (through **EventEntity**)
- **Event** N—N **Category** (through **EventCategory**)
- **Event** 1—N **Claim**
- **Event** 1—N **ProcessingResult**
- **Source** 1—N **SourceHealth**
- **Source** 1—N **IngestionJob**
- **User** 1—N **SavedItem**

### I3. Historical Preservation

- **Events** are versioned. When an event is updated (new source added, summary regenerated), a new row is created with an incremented `version` and a `superseded_by` pointer.
- **Articles** are immutable once fetched. If the source updates the article, a new article record is created with a reference to the original.
- **SourceHealth** is a time-series table — never overwritten.
- **Corrections** are append-only — the original value is preserved.

---

## J. Architecture

### J1. Recommended Architecture (V1)

```text
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                        │
│  Card Feed · Search · Filters · Event Detail · Admin Panel   │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / tRPC
┌──────────────────────────▼──────────────────────────────────┐
│                    API LAYER (FastAPI)                        │
│  Events API · Search API · Sources API · Admin API           │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 EVENT INTELLIGENCE PIPELINE                   │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │
│  │ Fetcher │→│Normalizer│→│Dedup     │→│ Clusterer     │   │
│  └─────────┘ └──────────┘ └──────────┘ └───────┬───────┘   │
│                                                  │           │
│  ┌───────────────────────────────────────────────▼───────┐  │
│  │              Enrichment Service (LLM)                  │  │
│  │  Classification · Summarization · Entity Extraction   │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    STORAGE LAYER                              │
│  PostgreSQL (relational + FTS) · pgvector (embeddings)       │
│  Object Storage (raw content archives)                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    JOB QUEUE                                  │
│  Scheduled ingestion · Retry · Dead-letter                    │
└─────────────────────────────────────────────────────────────┘
```

### J2. Scheduling Architecture

**Recommended: Tiered polling with a scheduler service.**

| Tier | Update Frequency | Polling Interval | Examples |
|---|---|---|---|
| High | >3 updates/day | Every 15 minutes | OpenAI news, GitHub releases for active repos |
| Medium | 1–3 updates/day | Every 60 minutes | Most company blogs |
| Low | <1 update/day | Every 6 hours | arXiv, policy sources |

- Feeds are classified on first ingest based on historical update frequency.
- Classification is re-evaluated every 7 days based on actual update history.
- Conditional GET headers are sent on every request to minimize bandwidth.
- WebSub-enabled feeds skip polling entirely and receive push updates.

### J3. Why Not Every Source Every 20 Minutes

Naive polling of every source every 20 minutes does not scale:

- A registry of 200 sources polled every 20 minutes generates 14,400 requests/day.
- Most feed hosts will throttle or block clients that poll too frequently.
- Most sources do not update every 20 minutes — polling them at that cadence wastes bandwidth and increases the risk of rate limiting.
- Tiered polling reduces request volume by 60–80% while maintaining freshness for sources that actually update frequently.

The 20-minute freshness target applies to the **highest-frequency sources**. Medium and low-frequency sources are polled at intervals appropriate to their actual update cadence.

---

## K. Technology Stack

### K1. Frontend

| Technology | Recommendation | Justification |
|---|---|---|
| Framework | **Next.js** (React) | Server-side rendering for fast initial page load; API routes for simple backend integration; strong ecosystem for card/tile layouts |
| Language | **TypeScript** | Type safety across API contracts and component props |
| Styling | **Tailwind CSS** | Rapid, consistent UI development; excellent dark mode support |
| State | **TanStack Query** | Server state management with caching, pagination, and optimistic updates |

### K2. Backend

| Technology | Recommendation | Justification |
|---|---|---|
| API Framework | **FastAPI** (Python) | Async-native; automatic OpenAPI documentation; Pydantic validation; strong ecosystem for NLP/ML libraries |
| Worker Framework | **Python workers** | Reuse of NLP libraries (spaCy, sentence-transformers, feedparser) |
| Language | **Python 3.12+** | |

### K3. Database

| Technology | Recommendation | Justification |
|---|---|---|
| Primary DB | **PostgreSQL 16+** | Reliable, mature, excellent JSON support, full-text search built in |
| Vector Search | **pgvector** | Avoid introducing a separate vector database in V1. pgvector offers 0.987 recall@k at 1,800 QPS and 28ms latency — sufficient for the expected scale. |

> **Recommendation:** Do not introduce a dedicated vector database (Pinecone, Qdrant, Weaviate) in V1. pgvector is sufficient for 10,000+ events and avoids operational complexity. Re-evaluate only if semantic search latency exceeds 1s at p95.

### K4. Job Queue

| Technology | Recommendation | Justification |
|---|---|---|
| Queue | **BullMQ** (Redis) or **pg-boss** (PostgreSQL) | BullMQ is feature-rich and handles rate-limited, delayed, and repeatable jobs well. pg-boss avoids a Redis dependency. |

> **Recommendation:** Start with **pg-boss** to minimize operational dependencies (one less service to run). Migrate to BullMQ + Redis only if queue throughput becomes a bottleneck.

### K5. Hosting

| Option | Recommendation | Notes |
|---|---|---|
| **Vercel** (frontend) + **Railway/Fly.io** (backend + DB) | Good for small teams | Low operational overhead; Vercel free tier available |
| **AWS** (ECS + RDS + ElastiCache) | Better for enterprise integration | Higher operational complexity; higher cost |
| **GCP** (Cloud Run + Cloud SQL) | Balanced option | Serverless containers; generous free tier |
| **Azure** (App Service + Azure Database) | If organization is Microsoft-centric | Integration with Azure OpenAI Service |

> **Recommendation for V1:** Start with **Vercel (frontend) + Railway or Fly.io (backend + PostgreSQL)**. This minimizes operational overhead and allows the team to focus on the intelligence pipeline rather than infrastructure. Re-evaluate hosting once the system is stable and requirements for enterprise integration (e.g., SSO, VPC) are clear.

### K6. Open-Source Component Summary

| Component | Recommended Library | License | Notes |
|---|---|---|---|
| RSS parsing | `feedparser` (Python) | BSD | Best-in-class malformed XML handling |
| Web crawling | `Crawl4AI` or `trafilatura` | Apache 2.0 / MIT | For sources without RSS |
| NER | `spaCy` | MIT | Fast, reliable entity extraction |
| Embeddings | `sentence-transformers` (local) or OpenAI embeddings | Apache 2.0 / Proprietary | Local model for cost control; API for quality |
| Clustering | `scikit-learn` (HDBSCAN) | BSD | Deterministic, well-understood |
| Deduplication | `datasketch` (MinHash LSH) | MIT | Sub-linear time complexity |
| Full-text search | PostgreSQL `tsvector` | PostgreSQL License | No additional service required |
| Vector search | `pgvector` | PostgreSQL License | Extension for PostgreSQL |
| LLM SDK | `openai`, `anthropic`, `google-genai` | MIT / Proprietary | See §M for provider strategy |
| Observability | `OpenTelemetry` + `Grafana` / `Langfuse` | Apache 2.0 / MIT | For pipeline tracing and LLM cost tracking |
| Auth | `Auth.js` (NextAuth) or `Zitadel` | ISC / Apache 2.0 | SSO via SAML/OIDC |

---

## L. UX / Information Architecture

### L1. Homepage — Card Feed

**Layout:** Responsive grid of cards (3 columns desktop, 2 columns tablet, 1 column mobile).

**Card anatomy:**

| Element | Description |
|---|---|
| Headline | Event title (AI-generated, ≤80 chars) |
| One-line summary | Short summary (≤140 chars) |
| Source tier badge | Primary (green) / Secondary (blue) / Community (gray) |
| Category tags | 1–3 category chips |
| Organization tags | 1–3 organization chips |
| Time | Publication time (relative: "2h ago") |
| Importance indicator | Visual weight (e.g., border color or dot) |
| Action | "Read more" link to event detail |

**"New since last visit":** A visual indicator (e.g., blue dot or "NEW" label) on cards published since the user's last visit. The timestamp of the last visit is stored in `localStorage` or user preferences.

### L2. Filters

| Filter | Type | Options |
|---|---|---|
| Date range | Preset | Today, Last 7 days, Last 30 days, Custom |
| Category | Multi-select | Foundation Models, Agents, Coding, Open Source, Infrastructure, Research, Policy, Funding, etc. |
| Organization | Multi-select | OpenAI, Anthropic, Google, Meta, etc. |
| Source tier | Multi-select | Primary, Secondary, Community |
| Importance | Single-select | All, High, Medium, Low |
| Search | Text input | Keyword search across event titles and summaries |

### L3. Event Detail Page

| Section | Content |
|---|---|
| Header | Event title, importance indicator, publication/detection time |
| Summary | AI-generated short summary |
| What Changed | Concise description of the actual change |
| Why It Matters | Concise assessment of significance |
| Sources | List of source articles with: source name, tier badge, title, publication time, link to original |
| Entities | Linked organization, product, model, and people chips |
| Related Events | Similar or precursor events |
| Provenance | Full chain: event → articles → sources → fetch timestamps |

### L4. Search

- **Keyword search:** Full-text search across event titles, summaries, and article titles using PostgreSQL `tsvector`.
- **Semantic search:** Vector similarity search across event embeddings using pgvector.
- **Hybrid search:** Combine keyword and semantic results, re-rank by relevance.

### L5. Accessibility

- Keyboard navigation for all interactive elements.
- ARIA labels on filter controls and card actions.
- Minimum contrast ratios per WCAG 2.1 AA.
- Screen-reader-friendly event detail structure.

---

## M. AI/LLM Architecture

### M1. Provider Strategy

**Recommendation: Multi-provider with abstraction layer.**

| Provider | Use Case | Fallback |
|---|---|---|
| **OpenAI** (GPT-5 series) | Primary for summarization, classification, entity extraction | Anthropic Claude |
| **Anthropic** (Claude) | Primary for coding-related events and structured output | OpenAI GPT |
| **Google** (Gemini) | Primary for long-context event clustering (when >100 articles in a cluster) | OpenAI |
| **Open-weight / local** (e.g., Llama, Qwen via Ollama) | Fallback for cost control; batch processing | Any API provider |

**Abstraction layer:** Use an LLM gateway (e.g., **LiteLLM** or **Portkey**) to standardize provider APIs, handle fallback, track costs, and enforce rate limits.

### M2. Structured Output

All LLM calls for classification, entity extraction, and summarization must use **structured output** (JSON schema enforcement). This ensures:

- Consistent output format across providers.
- Programmatic validation before storage.
- Reduced hallucination surface (the model must fill required fields).

### M3. Summarization Architecture

**Recommendation: Event-level summarization with claim anchoring.**

1. **Extract claims** from each article in the event cluster: atomic factual statements with token-level provenance.
2. **Cluster equivalent claims** across articles; flag conflicts.
3. **Select salient, support-aware claims** for the summary.
4. **Rewrite** into a coherent summary where every sentence is anchored to a support-checked claim that links back to source spans.

This approach improves citation precision and faithfulness compared to end-to-end summarization.

### M4. Hallucination Prevention

| Technique | Application |
|---|---|
| Low temperature (0–0.2) | All factual summarization and classification calls |
| Citation-grounded generation | Require the model to cite specific source spans for each claim |
| Claim anchoring | Every summary sentence must link to a source span |
| Structured output | JSON schema enforcement for all classification and extraction |
| Post-generation verification | Automated check that every claim in the summary is supported by at least one cited source |
| Human review flag | Summaries with low confidence or detected conflicts flagged for admin review |

### M5. Cost Control

| Strategy | Implementation |
|---|---|
| Cache summaries | Once an event is summarized, do not re-summarize unless new sources are added |
| Batch processing | Batch embeddings and classification calls where possible |
| Model tiering | Use cheaper models (e.g., GPT-5-mini, Claude Haiku) for classification; use frontier models only for summarization |
| Token budgeting | Set daily/monthly LLM budget limits; fail closed when exceeded |
| Embedding model | Use `text-embedding-3-small` ($0.02/M tokens) for clustering rather than `text-embedding-3-large` ($0.13/M tokens) |

---

## N. Security Architecture

### N1. Threat Model

| Threat | Description | Mitigation |
|---|---|---|
| **Prompt injection from crawled content** | Malicious content in an article instructs the LLM to ignore its instructions | Input sanitization; structured prompt formatting; output validation |
| **SSRF** | An attacker provides a URL that causes the server to make requests to internal services | URL allowlist; DNS resolution validation; network segmentation |
| **Malicious GitHub content** | A repository contains malicious code or content designed to exploit the crawler | Treat all fetched content as untrusted; never execute fetched code |
| **API key leakage** | LLM provider API keys exposed in logs or client-side code | Server-side only; encrypted at rest; never logged |
| **Data isolation** | One user's saved items visible to another | Row-level security in PostgreSQL; user-scoped queries |
| **Unauthorized access** | External party accesses the internal tool | SSO required; no public access |
| **Unsafe URLs** | Links to malicious sites in event detail pages | URL validation; warning interstitial for external links |

### N2. Authentication & Authorization

- **SSO required** via SAML or OIDC (integrate with organizational identity provider).
- **Roles:** `Admin` (full access, source management, corrections), `User` (read, search, save), `Viewer` (read-only).
- **Audit log** for all administrative actions.

### N3. Content Security

- All crawled content is stored as raw data and never rendered as HTML in the application.
- LLM prompts that include crawled content must delimit it clearly and instruct the model to treat it as untrusted data.
- External links open in a new tab with `rel="noopener noreferrer"`.

---

## O. Cost Model

### O1. Assumptions

| Parameter | Value | Notes |
|---|---|---|
| Sources monitored | 150–200 | V1 target |
| Average articles/day | 200–500 | Across all sources |
| Events/month | 1,000 (small) / 5,000 (medium) / 15,000 (large) | |
| Embedding model | `text-embedding-3-small` | $0.02/M tokens |
| Summarization model | GPT-5-class | $1.25–$5.00/M input; $10–$30/M output |
| Classification model | GPT-5-mini-class | ~$0.15/M input |
| Average tokens per article | ~2,000 | |
| Average articles per event | ~3 | |
| Summarization tokens per event | ~2,000 input, ~500 output | |

### O2. Estimated Monthly Costs

| Component | Small (1K events/mo) | Medium (5K events/mo) | Large (15K events/mo) |
|---|---|---|---|
| **Hosting** (Vercel + Railway) | $20–$50 | $50–$150 | $150–$400 |
| **PostgreSQL** (managed) | $15–$30 | $30–$80 | $80–$200 |
| **Redis** (if used) | $0–$15 | $15–$30 | $30–$60 |
| **Embeddings** | ~$0.50 | ~$2.50 | ~$7.50 |
| **Classification** (LLM) | ~$1.50 | ~$7.50 | ~$22.50 |
| **Summarization** (LLM) | ~$15–$40 | ~$75–$200 | ~$225–$600 |
| **Source APIs** (NewsAPI, etc.) | $0–$50 | $50–$100 | $100–$450 |
| **Object storage** | $1–$5 | $5–$15 | $15–$30 |
| **Monitoring** | $0–$20 | $20–$50 | $50–$100 |
| **Total (estimated)** | **$55–$210** | **$250–$625** | **$650–$1,860** |

> **Note:** These estimates assume efficient batching and caching. LLM summarization dominates cost at scale. The $450/month figure for a single Claude Opus news bot provides a real-world reference point. The range above assumes model tiering (cheaper models for classification, frontier models only for summarization).

### O3. Cost Control Levers

1. **Reduce summarization frequency:** Only summarize events with ≥2 sources or primary-source events.
2. **Batch embeddings:** Embed articles in batches rather than individually.
3. **Use cheaper models for non-critical tasks:** Classification and entity extraction can use smaller models.
4. **Cache aggressively:** Do not re-summarize unless the event changes.
5. **Set hard budget caps:** Fail closed when the monthly LLM budget is exceeded.

---

## P. Testing Strategy

### P1. Test Categories

| Category | Scope | Acceptance Criteria |
|---|---|---|
| **Unit tests** | Individual functions: feed parsing, deduplication, entity extraction, category classification | ≥90% code coverage for core logic |
| **Integration tests** | Pipeline stages: fetch → normalize → deduplicate → cluster | End-to-end processing of a fixture dataset produces expected events |
| **Source ingestion tests** | Live and fixture-based fetching from each source type | ≥95% of sources successfully fetched in a 24-hour test window |
| **Parser tests** | RSS/Atom/JSON parsing across malformed inputs | Handles malformed XML, encoding issues, missing fields without crashing |
| **Deduplication tests** | Near-duplicate detection with labeled pairs | <5% false positive; <2% false negative |
| **Event clustering tests** | Clustering of labeled article groups | Adjusted Rand Index ≥ 0.80 on test set |
| **LLM evaluation** | Summarization factuality, citation accuracy | >95% of claims supported by cited source |
| **Provenance tests** | Every event traceable to source articles | 100% of events have complete provenance chain |
| **Security tests** | Prompt injection, SSRF, XSS | No successful injection in a defined attack suite |
| **Load tests** | Concurrent user access, high ingestion volume | Homepage <2s at 50 concurrent users |
| **Failure recovery tests** | Source outage, queue failure, DB failure | System recovers within 5 minutes of service restoration |
| **End-to-end tests** | Full pipeline from source to UI | New event appears in feed within 20 minutes (high-tier sources) |

### P2. LLM Evaluation

- **Factuality:** Human evaluation of a random sample of 100 event summaries per month. Each claim is checked against cited sources.
- **Citation accuracy:** Automated check that every claim in the summary is supported by at least one cited source span.
- **Consistency:** Run the same event through the summarization pipeline multiple times; measure variance in key claims.
- **Regression testing:** Maintain a golden dataset of events with human-approved summaries; evaluate each pipeline change against it.

---

## Q. Observability

### Q1. Metrics to Monitor

| Category | Metric | Alert Threshold |
|---|---|---|
| **Source health** | Fetch success rate per source | <90% over 24h |
| **Source health** | Sources failing 3+ consecutive fetches | Any |
| **Ingestion** | Documents fetched/hour | <50% of 7-day average |
| **Ingestion** | Ingestion job latency (p95) | >5 minutes |
| **Deduplication** | Duplicate rate | >80% (potential source loop) |
| **Event creation** | New events/day | <20% of 7-day average |
| **Clustering** | Events with >20 articles | Any (potential over-clustering) |
| **LLM** | LLM API failure rate | >5% |
| **LLM** | LLM cost/day | >120% of daily budget |
| **LLM** | Summarization latency (p95) | >30 seconds |
| **Pipeline** | End-to-end latency (source publish → event visible) | >30 minutes |
| **Database** | Query latency (p95) | >500ms |
| **Queue** | Queue depth | >1,000 pending jobs |
| **Frontend** | Page load time (p95) | >3 seconds |
| **Frontend** | JavaScript error rate | >1% of sessions |

### Q2. Operational Dashboard

A single-page dashboard showing:

- Source health grid (green/yellow/red per source)
- Ingestion throughput (articles/hour, 24h trend)
- Event creation rate (events/day, 30-day trend)
- LLM cost accumulation (daily, monthly, against budget)
- Queue depth and job latency
- Pipeline end-to-end latency
- Error rate by component

---

## R. Risk Register

| Risk | Probability | Impact | Mitigation | Detection |
|---|---|---|---|---|
| **Information overload** | High | Medium | Event clustering; importance scoring; category filters | User feedback; feed engagement metrics |
| **False importance** | Medium | Medium | Human-reviewable importance rubric; admin corrections | Sample audit of high-importance events |
| **Missed important events** | Medium | High | Broad source coverage; community source monitoring; gap analysis | Weekly review of "what did we miss?" against external sources |
| **Hallucinated summaries** | Medium | High | Claim anchoring; citation verification; low temperature; human review flags | Automated claim-support check; monthly human evaluation |
| **Incorrect event grouping** | Medium | Medium | Tunable clustering thresholds; manual merge/split; admin review | User reports; cluster size monitoring |
| **Source bias** | Medium | Medium | Diverse source registry; primary-source preference; tier labeling | Source diversity audit; bias review in summaries |
| **Source outages** | High | Low | Redundant sources; degraded source handling; backoff | Source health dashboard |
| **API cost explosion** | Medium | High | Budget caps; model tiering; caching; batch processing | Daily cost monitoring; alerts |
| **Crawler maintenance** | High | Medium | Prefer RSS/API over crawling; monitor parser health; modular source adapters | Parser failure alerts |
| **Legal restrictions** | Medium | High | Legal review; prefer metadata + links over full text; respect robots.txt | Legal review before V1 launch |
| **Prompt injection** | Medium | High | Input sanitization; structured prompts; output validation | Security testing; anomaly detection |
| **Malicious source content** | Low | High | Treat all content as untrusted; never execute fetched code | Security review; content scanning |
| **Vendor lock-in** | Medium | Medium | Multi-provider LLM abstraction; open-source core components | Architecture review |
| **Overengineering** | High | Medium | Strict V1 scope; phased roadmap; avoid premature optimization | Scope review at each phase gate |
| **Excessive latency** | Medium | Medium | Async pipeline; caching; tiered polling | Latency monitoring |
| **Poor UX** | Medium | High | User testing; card-feed pattern validated by existing products | User feedback; engagement metrics |
| **Low organizational adoption** | Medium | High | Involve users in requirements; start with a small pilot; iterate | Usage metrics; user interviews |

---

## S. V1 Scope

### MUST HAVE

- Source registry with 50–100 curated sources (primary + selected secondary/community).
- Tiered polling scheduler (15 min / 60 min / 6 hours).
- RSS/Atom and GitHub Releases ingestion.
- Deterministic deduplication (MinHash LSH / Jaccard).
- Embedding-based event clustering (pgvector + HDBSCAN).
- LLM summarization at event level with citation anchoring.
- PostgreSQL storage with pgvector.
- Card-feed homepage with filters (date, category, organization, source tier).
- Event detail page with provenance display.
- Keyword + semantic search.
- SSO authentication.
- Admin panel for source management and event corrections.
- Source health monitoring.

### SHOULD HAVE

- Community source monitoring (Hacker News API).
- "New since last visit" indicator.
- Saved items.
- Dark/light mode.
- Basic observability dashboard.

### COULD HAVE

- WebSub support for push-based feeds.
- Automated source discovery from secondary-source citations.
- Conflict detection across sources.
- Export to Slack/Teams.
- User-defined alerts.

### NOT IN V1

- Real-time social media monitoring (X/Twitter firehose).
- Full-text article storage (store excerpts + links).
- Custom ML models for importance scoring.
- Multi-tenant / external user support.
- Mobile native app.
- Automated event merging without human review.
- Podcast/video source monitoring.

---

## T. Phased Roadmap

### Phase 0 — Research & Requirements (2–3 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Validate requirements, finalize source registry, define acceptance criteria |
| **Deliverables** | Source registry spec; data model; architecture decision record; V1 scope sign-off |
| **Dependencies** | Stakeholder interviews |
| **Acceptance criteria** | Signed-off PRD and architecture document |
| **Risks** | Scope creep; unclear ownership |
| **Must NOT build** | Any production code |

### Phase 1 — Source Registry + Ingestion (3–4 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Build source registry and ingestion pipeline for RSS/GitHub sources |
| **Deliverables** | Source registry CRUD; fetch scheduler; feed parser; raw article storage; source health tracking |
| **Dependencies** | Phase 0 |
| **Acceptance criteria** | 50+ sources successfully ingested; source health dashboard operational |
| **Risks** | Feed parsing edge cases; rate limiting |
| **Must NOT build** | Event clustering, LLM summarization, frontend |

### Phase 2 — Event Detection + Deduplication (3–4 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Transform raw articles into deduplicated event clusters |
| **Deliverables** | Near-duplicate detection; embedding pipeline; HDBSCAN clustering; event versioning |
| **Dependencies** | Phase 1 |
| **Acceptance criteria** | <5% false positive dedup rate; ARI ≥ 0.80 on test set |
| **Risks** | Clustering threshold tuning; embedding model selection |
| **Must NOT build** | LLM summarization, frontend |

### Phase 3 — AI Analysis + Summaries (3–4 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Enrich events with classification, entity extraction, and source-grounded summaries |
| **Deliverables** | LLM gateway; classification service; entity extraction; claim-anchored summarization; cost tracking |
| **Dependencies** | Phase 2 |
| **Acceptance criteria** | >95% claim support rate; LLM cost within budget |
| **Risks** | Hallucination; provider outages; cost overruns |
| **Must NOT build** | Frontend |

### Phase 4 — Database + Search (2–3 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Finalize storage schema and implement search |
| **Deliverables** | PostgreSQL schema; pgvector indexes; FTS; hybrid search API |
| **Dependencies** | Phase 3 |
| **Acceptance criteria** | Search latency <500ms (keyword), <1s (semantic) |
| **Risks** | Schema migration; index performance |
| **Must NOT build** | Frontend |

### Phase 5 — Web Dashboard (3–4 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Build the card-feed homepage, event detail page, and search UI |
| **Deliverables** | Next.js frontend; card feed; filters; event detail; search; dark/light mode |
| **Dependencies** | Phase 4 |
| **Acceptance criteria** | Homepage load <2s (p95); all filters functional |
| **Risks** | UX complexity; performance |
| **Must NOT build** | Advanced features (alerts, exports) |

### Phase 6 — Internal Organization Features (2–3 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Add SSO, roles, saved items, admin panel, audit log |
| **Deliverables** | SSO integration; RBAC; saved items; admin panel; audit log |
| **Dependencies** | Phase 5 |
| **Acceptance criteria** | SSO login works; admin actions logged |
| **Risks** | Identity provider integration |
| **Must NOT build** | External user access |

### Phase 7 — Reliability/Security Hardening (2–3 weeks)

| Aspect | Detail |
|---|---|
| **Objective** | Harden security, improve reliability, complete observability |
| **Deliverables** | Security testing; prompt injection defenses; failure recovery; observability dashboard |
| **Dependencies** | Phase 6 |
| **Acceptance criteria** | No successful injection in attack suite; system recovers within 5 min |
| **Risks** | Security vulnerabilities; edge cases |
| **Must NOT build** | New features |

### Phase 8 — Advanced Intelligence (Ongoing)

| Aspect | Detail |
|---|---|
| **Objective** | Add advanced features based on user feedback |
| **Deliverables** | WebSub; automated source discovery; conflict detection; alerts; exports |
| **Dependencies** | Phase 7 |
| **Acceptance criteria** | Defined per feature |
| **Risks** | Scope creep |
| **Must NOT build** | Anything not prioritized by users |

---

## U. Acceptance Criteria

| Phase | Acceptance Criteria |
|---|---|
| Phase 1 | ≥50 sources ingested; source health dashboard shows ≥90% healthy sources |
| Phase 2 | Dedup false-positive rate <5%; clustering ARI ≥0.80 |
| Phase 3 | Summary claim support rate >95%; LLM cost within monthly budget |
| Phase 4 | Search latency: keyword <500ms, semantic <1s (p95) |
| Phase 5 | Homepage load <2s (p95); all filters functional; event detail page complete |
| Phase 6 | SSO functional; RBAC enforced; audit log complete |
| Phase 7 | Security attack suite passed; failure recovery <5 minutes |
| Phase 8 | Per-feature acceptance criteria defined at start of each feature |

---

## V. Open Questions

| # | Question | Impact | Owner |
|---|---|---|---|
| 1 | Which SSO provider will be used? (Okta, Azure AD, Google Workspace, etc.) | Authentication implementation | IT / Platform team |
| 2 | Is there an existing LLM API contract or budget? | Provider selection and cost model | Finance / Platform team |
| 3 | What is the maximum acceptable monthly LLM spend? | Cost control and model tiering strategy | Product owner |
| 4 | Should the system store full article text or only excerpts + links? | Legal review; storage cost | Legal / Product owner |
| 5 | What is the organization's policy on crawling sources without RSS? | Source coverage | Legal / Product owner |
| 6 | Should the system integrate with Slack/Teams for notifications in V1? | Scope and UX | Product owner |
| 7 | How many concurrent users are expected? | Performance targets and hosting | Product owner |
| 8 | Should the system support multiple languages (e.g., Chinese AI labs)? | NLP pipeline complexity | Product owner |
| 9 | What is the retention policy for raw article content? | Storage cost and legal | Legal / Product owner |
| 10 | Should the system expose a public API for other internal tools? | Architecture and scope | Architecture team |
| 11 | What is the expected event volume in the first 6 months? | Cost model validation | Product owner |
| 12 | Should community sources (Hacker News, Reddit) be monitored in V1 or deferred? | Scope and noise management | Product owner |
| 13 | What is the process for correcting an incorrect AI-generated summary? | Admin workflow | Product owner |
| 14 | Should the system support user-defined custom sources? | Admin scope and source health | Product owner |
| 15 | What is the SLA for source health alerts? | Observability requirements | Platform team |

---

*This research report is intended to feed directly into a Product Requirements Document (PRD), System Architecture Document, Database Schema, API Specification, Source Registry Specification, AI Processing Specification, UI/UX Specification, Security Requirements, Test Plan, and Phased Engineering Roadmap. All facts, claims, and recommendations are distinguished throughout. Where information is uncertain or unavailable, this is stated explicitly. Verify all external facts, APIs, pricing, and licenses before implementation.*