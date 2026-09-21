# Implementation Roadmap

The execution plan for the AI World Intelligence Platform. Phases may overlap where dependencies permit.

## PHASE 0: Requirements / Architecture (IN PROGRESS)
- [x] Initial workspace inspection.
- [x] Tech stack selection.
- [x] Core documentation generation (Architecture, Data Model, etc.).

## PHASE 1: Source Registry + Ingestion
- [ ] Initialize Python (FastAPI/Celery) backend environment.
- [ ] Implement database schemas (SQLAlchemy/Alembic).
- [ ] Implement data-driven Source Registry models.
- [ ] Build basic fetchers (RSS, API) and background task scheduling.

## PHASE 2: Deduplication + Event Intelligence
- [ ] Implement deterministic deduplication (URL, Title matching).
- [ ] Implement embedding-based vector search (pgvector) for clustering.
- [ ] Build logic for merging articles into events.

## PHASE 3: AI Enrichment
- [ ] Integrate LLM SDK (with strict Pydantic structured outputs).
- [ ] Implement source-grounded summarization logic.
- [ ] Implement importance scoring mechanism.

## PHASE 4: Storage + Search
- [ ] Finalize Postgres indexing.
- [ ] Implement metadata, keyword, and date filtering APIs.

## PHASE 5: Dashboard
- [ ] Initialize Next.js frontend with Tailwind CSS.
- [ ] Build the high-information-density card layout homepage.
- [ ] Build the event detail view (provenance, sources, summary).

## PHASE 6: Organization / Auth / Admin
- [ ] Implement authentication (mock OIDC/JWT for initial dev).
- [ ] Build Admin UI (source management, event splitting/merging).
- [ ] Implement user-level "New Since Last Visit" tracking.

## PHASE 7: Security & Reliability Hardening
- [ ] XSS/SSRF audits.
- [ ] Implement observability (logging, metrics, API failure rates).
- [ ] Run end-to-end regression tests with real source data.

## PHASE 8: Advanced Intelligence
- [ ] Conflict detection across contradictory sources.
- [ ] Automated entity resolution (e.g., tying "GPT-4" to "OpenAI").
