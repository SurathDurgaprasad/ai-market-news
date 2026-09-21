# Data Model

This document outlines the core relational schema for the AI World Intelligence Platform.
All tables must enforce strict foreign keys to preserve provenance.

## Core Entities

### 1. `Source`
Represents an origin of information.
- `id` (UUID, PK)
- `name` (String)
- `url` (String)
- `organization_id` (UUID, FK)
- `tier` (Enum: PRIMARY, SECONDARY, COMMUNITY)
- `type` (Enum: API, RSS, GITHUB, HTML)
- `polling_policy` (JSON: interval, rules)
- `is_active` (Boolean)
- `health_status` (JSON: last_fetch, fail_count)

### 2. `Organization`
Represents a company or research group (e.g., OpenAI, Google).
- `id` (UUID, PK)
- `name` (String, Unique)
- `domain` (String)

### 3. `Article` (Raw Ingestion)
Represents a single scraped/fetched piece of content.
- `id` (UUID, PK)
- `source_id` (UUID, FK)
- `url` (String, Unique)
- `title` (String)
- `raw_content` (Text)
- `published_at` (Timestamp)
- `ingested_at` (Timestamp)
- `hash` (String) - used for deduplication

### 4. `Event` (The Core Object)
Represents a synthesized development in the AI space.
- `id` (UUID, PK)
- `headline` (String)
- `short_summary` (String)
- `what_changed` (Text)
- `why_it_matters` (Text)
- `importance_score` (Integer 1-100)
- `importance_reasoning` (JSON)
- `primary_source_id` (UUID, FK)
- `created_at` (Timestamp)
- `updated_at` (Timestamp)

### 5. `EventArticle` (Join Table)
Maps multiple Articles to a single Event.
- `event_id` (UUID, FK)
- `article_id` (UUID, FK)
- `similarity_score` (Float)

### 6. `EventVersion`
Audit log of changes to an Event over time.
- `id` (UUID, PK)
- `event_id` (UUID, FK)
- `snapshot` (JSONB)
- `changed_at` (Timestamp)

### 7. `Entity` & `EventEntity`
Tracks models, products, and people (e.g., GPT-4, Ilya Sutskever).
- `id` (UUID, PK)
- `name` (String)
- `type` (Enum: MODEL, PRODUCT, PERSON, ORG)

### 8. `User` & `SavedEvent`
For user authentication and bookmarking.
- `id` (UUID, PK)
- `email` (String)
- `role` (Enum: USER, ADMIN)
- `last_visit_at` (Timestamp)
