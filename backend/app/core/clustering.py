from sqlalchemy.orm import Session
from app.models.event import Event
from app.models.article import Article
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

CLUSTER_MERGE_THRESHOLD = 0.85  # Cosine similarity threshold for automatic merge

# pgvector is only available in PostgreSQL environments.
try:
    from pgvector.sqlalchemy import Vector as _Vector  # noqa: F401
    _PGVECTOR_AVAILABLE = True
except ImportError:
    _PGVECTOR_AVAILABLE = False

def find_best_matching_event(db: Session, embedding: list[float]) -> Optional[Tuple[Event, float]]:
    """
    Search for the most semantically similar recent event using pgvector cosine distance.
    Returns a tuple of (Event, cosine_similarity) if a match is found above threshold,
    or None if pgvector is unavailable (SQLite test environment) or no match exists.

    NOTE: This function is NOT called by the primary pipeline, which uses a layered
    entity + LLM approach instead. This is a future upgrade path for full vector search.
    """
    if not _PGVECTOR_AVAILABLE:
        logger.debug("pgvector unavailable — vector clustering skipped")
        return None

    if db is None:
        return None

    try:
        # cosine_distance returns 0 (identical) to 2 (opposite)
        result = (
            db.query(Event, Event.embedding.cosine_distance(embedding).label("distance"))
            .filter(Event.embedding.isnot(None))
            .order_by("distance")
            .first()
        )
    except Exception as exc:
        logger.error(f"Vector clustering query failed: {exc}")
        return None

    if not result:
        return None

    event, distance = result
    similarity = 1.0 - (float(distance) / 2.0)  # normalize [0, 2] → [1, 0]
    return (event, similarity)

def attach_article_to_event_if_similar(
    db: Session,
    article: Article,
    embedding: list[float],
) -> Optional[Event]:
    """
    Vector-based clustering: attach an article to an existing event if cosine similarity
    exceeds CLUSTER_MERGE_THRESHOLD.  Returns the matched Event, or None if no match
    (caller is responsible for creating a new Event in that case).

    This is the vector-search upgrade path.  The primary pipeline currently uses
    a layered entity-overlap + LLM approach (pipeline.py) and calls this only
    when pgvector embeddings are available.
    """
    match = find_best_matching_event(db, embedding)
    if match:
        best_event, similarity = match
        if similarity >= CLUSTER_MERGE_THRESHOLD:
            logger.info(
                f"Vector match: article '{article.title}' → event '{best_event.headline}' "
                f"(similarity={similarity:.3f})"
            )
            return best_event
    return None
