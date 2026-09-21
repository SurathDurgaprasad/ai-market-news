# System Architecture

## 1. High-Level Architecture

The AI World Intelligence Platform follows a decoupled, service-oriented architecture designed for reliability, asynchronous processing, and high UI performance.

### 1.1 Components
- **Frontend (Next.js)**: A React-based web application providing the high-information-density dashboard and admin interfaces.
- **Backend API (FastAPI - Python)**: REST API serving the frontend, handling user sessions, database queries, search, and manual administration tasks.
- **Ingestion Workers (Celery + Python)**: Asynchronous workers handling fetching, deduplication, and AI processing.
- **Message Broker (Redis)**: Task queue for Celery.
- **Relational Database (PostgreSQL)**: Primary data store for events, articles, sources, and metadata. Uses `pgvector` for semantic similarity search/clustering.

## 2. Ingestion Pipeline Architecture

The pipeline processes data sequentially and idempotently:
1. **Source** -> **Fetch**: Retrieves raw data via API, RSS, or GitHub API.
2. **Normalize** -> **Validate**: Standardizes fields (Title, Date, Content) and ensures schema correctness.
3. **Deduplicate**: Deterministic checks (URL, exact title, canonical matching).
4. **Extract** -> **Cluster**: Identifies entities; uses embeddings to group with existing candidate events.
5. **Classify** -> **Analyze**: LLM evaluation (importance, categorization, claim extraction).
6. **Summarize** -> **Verify**: Source-grounded summarization. Checks for hallucinations.
7. **Store** -> **Index** -> **Display**: Saves to Postgres and makes it available to the API.

## 3. Data Integrity & Provenance
Every entity in the database maintains a strict lineage back to its origin URL.
- **Immutability**: Event updates create new versions rather than overwriting history.
- **Source Tiers**: Explicit tracking of Primary, Secondary, and Community sources.

## 4. Security & Authentication
- Internal auth via OIDC/SAML standard implementations.
- Content sanitization applied to all text before rendering to prevent XSS.
- The ingestion environment is sandboxed; no dynamic code execution is permitted.

## 5. Deployment
- Containerized via Docker.
- Environment variable-based configuration for API keys, DB URIs, and tunable parameters (polling intervals, thresholds).
