# Ingestion Pipeline

The ingestion pipeline is the critical background engine of the AI World Intelligence Platform.

## Pipeline Stages

### 1. Source -> Fetch
- **Mechanism**: CRON-scheduled Celery tasks based on source `polling_policy`.
- **Rules**: Rate limiting, exponential backoff on failure, respect `robots.txt` where applicable. Focus on APIs and RSS first.

### 2. Normalize -> Validate
- **Mechanism**: Python parsers transform varied inputs (RSS XML, JSON API, raw HTML) into a standard `Article` schema.
- **Rules**: Strip malicious HTML. Discard corrupted payloads.

### 3. Deduplicate
- **Mechanism**: Exact URL match, Canonical URL extraction, Title string matching, SimHash.
- **Rules**: Drop immediately if it is a 100% duplicate of an existing article to save LLM costs.

### 4. Extract -> Cluster
- **Mechanism**: Convert normalized text into vector embeddings (e.g., using `text-embedding-3-small`). Perform cosine similarity against recent events in `pgvector`.
- **Rules**: If similarity > `CLUSTER_MERGE_THRESHOLD`, append the `Article` to the existing `Event`. If between thresholds, flag for admin review. If below, create a new candidate `Event`.

### 5. Classify -> Analyze
- **Mechanism**: Send candidate Event + Articles to an LLM (e.g., GPT-4o-mini).
- **Rules**: Extract tags, evaluate importance across multiple dimensions (novelty, ecosystem impact). Force strict JSON output using Pydantic schemas.

### 6. Summarize -> Verify
- **Mechanism**: LLM writes the `headline`, `short_summary`, `what_changed`, and `why_it_matters`.
- **Rules**: The prompt MUST instruct the model to ground every claim in the source text.

### 7. Store -> Index -> Display
- **Mechanism**: Save to PostgreSQL. Push real-time updates via WebSockets or polling to the frontend.
