from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Any, Literal
from datetime import datetime, timezone
import uuid as uuid_module
from pydantic import BaseModel, ConfigDict, field_serializer
from app.db.session import get_db
from app.models.event import Event, EventArticle
from app.models.article import Article
from app.models.source import Source
from app.core.urls import sanitize_http_url
from app.core.presentation import classify_image_role, present_citations
from app.core.origin import resolve_originating_source
from app.core.feed import current_week_start, is_feed_in_scope

router = APIRouter()


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Emit timezone-aware UTC ISO strings so the dashboard does not shift naive SQLite datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class SourceResponse(BaseModel):
    name: str
    url: str
    tier: str
    model_config = ConfigDict(from_attributes=True)


class LinkedArticleResponse(BaseModel):
    """A source that has been linked to this event as supporting evidence."""
    title: str
    url: str
    source_name: str
    source_tier: str
    published_at: Optional[datetime] = None
    link_type: str  # "primary" | "supporting" | "additional"

    @field_serializer("published_at")
    def _ser_published_at(self, dt: Optional[datetime], _info):
        return _iso_utc(dt)


class EventResponse(BaseModel):
    id: str
    headline: str
    short_summary: str
    what_changed: Optional[str] = None
    importance_score: int
    importance_reasoning: Optional[Any] = None
    version: int = 1
    created_at: datetime
    # When the underlying event actually occurred (source publication time).
    # Falls back to created_at if not available.
    event_time: Optional[datetime] = None
    primary_source: Optional[SourceResponse] = None
    ingest_source: Optional[SourceResponse] = None
    official_source: Optional[SourceResponse] = None
    citations: List[str] = []
    image_url: Optional[str] = None
    image_role: Literal["hero", "source", "none"] = "none"
    article_url: Optional[str] = None
    # Actual entities extracted by the LLM (organizations, products, people)
    entities: List[str] = []
    mentioned_entities: List[str] = []
    # All linked articles (supporting sources / evidence provenance)
    linked_articles: List[LinkedArticleResponse] = []

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "event_time")
    def _ser_event_times(self, dt: Optional[datetime], _info):
        return _iso_utc(dt)


def _safe_http_url(url: Optional[str], *, keep_query: bool = False) -> Optional[str]:
    if not url:
        return None
    clean = url.split("#update-")[0]
    return sanitize_http_url(clean, keep_query=keep_query) or None


def _synthetic_source(name: Optional[str], url: Optional[str], tier: str = "secondary") -> Optional[SourceResponse]:
    if not name:
        return None
    return SourceResponse(name=name, url=_safe_http_url(url) or "", tier=tier)


def _event_response(
    event: Event,
    *,
    linked_articles: Optional[List[LinkedArticleResponse]] = None,
    include_reasoning: bool = False,
) -> EventResponse:
    image_url = _safe_http_url(event.image_url, keep_query=True)
    ingest = _source_response(event.primary_source)
    origin = resolve_originating_source(
        ingest_name=event.primary_source.name if event.primary_source else None,
        ingest_url=event.primary_source.url if event.primary_source else None,
        article_url=event.article_url,
        publisher_name=getattr(event, "official_source_name", None),
    )
    official = None
    display = ingest
    if origin.used_official:
        official = _synthetic_source(
            origin.official_name,
            origin.official_url,
            event.primary_source.tier if event.primary_source else "secondary",
        )
        display = official
    mentioned = event.mentioned_entities if getattr(event, "mentioned_entities", None) else []
    primary = event.entities if event.entities else []
    if include_reasoning:
        seen = {item.lower() for item in primary if isinstance(item, str)}
        extra = [item for item in mentioned if isinstance(item, str) and item.lower() not in seen]
        entities = primary + extra
    else:
        entities = primary
        extra = []
    return EventResponse(
        id=str(event.id),
        headline=event.headline,
        short_summary=event.short_summary,
        what_changed=event.what_changed,
        importance_score=event.importance_score,
        importance_reasoning=event.importance_reasoning if include_reasoning else None,
        version=event.version,
        created_at=event.created_at,
        event_time=event.event_time,
        primary_source=display,
        ingest_source=ingest,
        official_source=official,
        citations=present_citations(event.citations),
        image_url=image_url,
        image_role=classify_image_role(image_url),  # type: ignore[arg-type]
        article_url=_safe_http_url(event.article_url),
        entities=entities,
        mentioned_entities=extra if include_reasoning else [],
        linked_articles=linked_articles or [],
    )


def _source_response(source: Optional[Source]) -> Optional[SourceResponse]:
    if not source:
        return None
    return SourceResponse(
        name=source.name,
        url=_safe_http_url(source.url) or "",
        tier=source.tier,
    )


def _high_signal(query):
    """
    Minimum canonical event for the dashboard feed:
    valid title, meaningful factual summary, and a source URL when stored.
    Incomplete rows remain GET-able by id. Citations are not required.
    """
    return query.filter(
        func.length(func.trim(Event.headline)) > 0,
        func.length(func.trim(Event.short_summary)) > 0,
        func.length(func.trim(func.coalesce(Event.article_url, ""))) > 0,
    )


def _order_by_real_world_time(query):
    """
    Feed order is when the real-world event occurred.

    event_time is source publication time. created_at is ingestion time and is
    only a fallback when event_time is missing. A newly ingested old article
    must not jump above a more recent development. Version updates keep the
    original event_time, so they also do not bump to the top.
    """
    return query.order_by(
        func.coalesce(Event.event_time, Event.created_at).desc(),
        Event.created_at.desc(),
    )


def _build_linked_articles(db: Session, event_id) -> List[LinkedArticleResponse]:
    """
    Returns all articles linked to an event, ordered by link_type (primary first).
    Performs a single JOIN query: EventArticle → Article → Source.
    """
    rows = (
        db.query(EventArticle, Article, Source)
        .join(Article, EventArticle.article_id == Article.id)
        .join(Source, Article.source_id == Source.id)
        .filter(EventArticle.event_id == event_id)
        .order_by(EventArticle.link_type)  # "primary" sorts before "supporting"
        .all()
    )
    result = []
    for ea, article, source in rows:
        result.append(LinkedArticleResponse(
            title=article.title,
            url=_safe_http_url(article.url) or "",
            source_name=source.name,
            source_tier=source.tier,
            published_at=article.published_at,
            link_type=ea.link_type,
        ))
    return result


def _in_current_week(query, now: Optional[datetime] = None):
    """Keep events whose real-world time falls in the current ISO week (UTC)."""
    start = current_week_start(now)
    occurred = func.coalesce(Event.event_time, Event.created_at)
    return query.filter(occurred >= start)


@router.get("/", response_model=List[EventResponse])
def get_events(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=250),
    min_importance: Optional[int] = Query(None, ge=0, le=100),
    q: Optional[str] = Query(None, description="Search keyword"),
    organization_id: Optional[str] = None,
    scope: Optional[Literal["week"]] = Query(
        None,
        description="week = current ISO week, newest first, AI developments only",
    ),
):
    """
    Retrieve paginated high-signal events.

    Ordered by real-world event_time (fallback created_at), newest first.
    Superseded versions and events with an empty short_summary are excluded.
    Incomplete rows remain addressable by ID on the detail endpoint.
    scope=week limits the feed to the current Monday–Sunday UTC week and
    drops non-AI items from secondary and community sources.
    """
    query = db.query(Event).options(joinedload(Event.primary_source)).filter(
        Event.superseded_by_id.is_(None)
    )
    query = _high_signal(query)
    if scope == "week":
        query = _in_current_week(query)

    if min_importance is not None:
        query = query.filter(Event.importance_score >= min_importance)

    if q:
        search_pattern = f"%{q}%"
        query = query.filter(
            (Event.headline.ilike(search_pattern)) |
            (Event.short_summary.ilike(search_pattern)) |
            (Event.what_changed.ilike(search_pattern))
        )

    if organization_id:
        query = query.join(Source, Event.primary_source_id == Source.id)
        query = query.filter(Source.organization_id == organization_id)

    events = _order_by_real_world_time(query).offset(skip).limit(limit).all()
    if scope == "week":
        events = [
            event
            for event in events
            if is_feed_in_scope(
                event.headline,
                event.short_summary,
                event.primary_source.tier if event.primary_source else None,
            )
        ]

    # Linked articles are omitted from the list view for performance.
    # They are populated in the single-event detail endpoint.
    return [_event_response(event) for event in events]


@router.get("/new_count", response_model=dict)
def get_new_events_count(
    since: datetime,
    db: Session = Depends(get_db),
    scope: Optional[Literal["week"]] = Query(None),
):
    """
    Returns the count of non-superseded events created after the given timestamp.

    Timestamp semantics (do not confuse these):
    - created_at  = when the canonical Event row was inserted (ingestion time)
    - event_time  = when the underlying real-world event occurred (source published_at)
    - ingested_at = when the Article row was inserted
    - published_at = source-declared publication time on the article
    - updated_at  = last DB update of the Event row

    new_count uses created_at, NOT event_time, and only counts high-signal
    events (non-empty short_summary). Incomplete extractions do not increment
    the chip because they are excluded from the dashboard feed.

    That means:
    - An old article newly discovered counts as new (created_at is now).
    - Attaching another source to an existing event does NOT increment the count
      (same canonical event, created_at unchanged).
    - Five supporting articles on one event still count as 0 new events after `since`.
    - A same-URL content update creates a new versioned event, which DOES count
      (new created_at; the old row is superseded and excluded).
      Product decision: material updates are a new canonical version, not a
      silent in-place edit, so the "N new events" chip can surface them.
    """
    query = _high_signal(
        db.query(Event).filter(
            Event.created_at > since,
            Event.superseded_by_id.is_(None),
        )
    )
    if scope == "week":
        rows = (
            _in_current_week(query)
            .options(joinedload(Event.primary_source))
            .all()
        )
        count = sum(
            1
            for event in rows
            if is_feed_in_scope(
                event.headline,
                event.short_summary,
                event.primary_source.tier if event.primary_source else None,
            )
        )
        return {"new_events_count": count}
    return {"new_events_count": query.count()}


@router.get("/{event_id}", response_model=EventResponse)
def get_event(event_id: str, db: Session = Depends(get_db)):
    """
    Retrieve a single canonical event with full provenance.
    Includes all linked articles (primary source + supporting evidence).
    """
    try:
        event_uuid = uuid_module.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    event = db.query(Event).filter(Event.id == event_uuid).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return _event_response(
        event,
        linked_articles=_build_linked_articles(db, event.id),
        include_reasoning=True,
    )
