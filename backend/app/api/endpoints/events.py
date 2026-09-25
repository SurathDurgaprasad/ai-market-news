from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional, Any, Literal
from datetime import datetime, timedelta, timezone
import uuid as uuid_module
from pydantic import BaseModel, ConfigDict, field_serializer
from app.db.session import get_db
from app.models.event import Event, EventArticle
from app.models.article import Article
from app.models.source import Source
from app.core.urls import sanitize_http_url
from app.core.presentation import classify_image_role, present_citations
from app.core.origin import evidence_tier_for_origin, host_of, resolve_originating_source
from app.core.feed import current_week_start, is_feed_in_scope
from app.core.market import (
    PLAYERS,
    MarketEvent,
    build_market_overview,
    event_matches_player,
    market_category,
    matching_players,
)
from app.core.providers.llm import LLM_UNAVAILABLE, resolve_llm_mode

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


class RelatedEventResponse(BaseModel):
    """Another live development that shares an organization or topic."""
    id: str
    headline: str
    event_time: Optional[datetime] = None
    category: str = ""
    reason: str

    @field_serializer("event_time")
    def _ser_event_time(self, dt: Optional[datetime], _info):
        return _iso_utc(dt)


class PreviousVersionResponse(BaseModel):
    """An earlier version of the same source page, replaced by a material edit."""
    id: str
    version: int
    headline: str
    recorded_at: datetime

    @field_serializer("recorded_at")
    def _ser_recorded_at(self, dt: datetime, _info):
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
    # Market category from the event's primary subject (same rule as the overview).
    category: str = ""
    # All linked articles (supporting sources / evidence provenance)
    linked_articles: List[LinkedArticleResponse] = []
    # Set when this row was merged into another canonical event. The detail
    # page follows canonical_id so an old link never shows an empty card.
    superseded_by_id: Optional[str] = None
    canonical_id: Optional[str] = None
    related: List[RelatedEventResponse] = []
    # Distinct publishers whose articles are merged into this event.
    source_count: int = 1
    # A material edit of the source page replaced an earlier version. False
    # for versions recorded only because page chrome or counters changed.
    is_update: bool = False
    # Earlier versions of the same page, newest first (detail view only).
    previous_versions: List[PreviousVersionResponse] = []

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


def _primary_hosts(db: Session) -> set:
    """Registrable hosts of curated primary sources, for validating an origin."""
    return {
        host_of(url)
        for (url,) in db.query(Source.url).filter(Source.tier == "primary").all()
        if url
    }


def _event_response(
    event: Event,
    *,
    linked_articles: Optional[List[LinkedArticleResponse]] = None,
    include_reasoning: bool = False,
    primary_hosts: Optional[set] = None,
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
        # The originating publisher behind an aggregator link. It is an
        # official source only when its host is a registered primary source;
        # otherwise it is the original article, not an official statement.
        # The aggregator's own tier (community) never describes the origin.
        tier = evidence_tier_for_origin(origin, primary_hosts or set()) or "origin"
        official = _synthetic_source(origin.official_name, origin.official_url, tier)
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
    reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
    return EventResponse(
        is_update=(event.version or 1) > 1 and "churn_created_at" not in reasoning,
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
        category=market_category(_to_market_event(event, [])) or "",
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
    pages = set()
    for ea, article, source in rows:
        page = _safe_http_url(article.url) or ""
        # Versions of one page are one piece of evidence, not extra coverage.
        if page and page in pages:
            continue
        pages.add(page)
        result.append(LinkedArticleResponse(
            title=article.title,
            url=page,
            source_name=source.name,
            source_tier=source.tier,
            published_at=article.published_at,
            link_type=ea.link_type,
        ))
    return result


def _to_market_event(event: Event, sources: list, primary_hosts: Optional[set] = None) -> MarketEvent:
    reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
    organization = ""
    primary_name = ""
    if event.primary_source is not None:
        primary_name = event.primary_source.name or ""
        if event.primary_source.organization is not None:
            organization = event.primary_source.organization.name or ""
    names: list[str] = []
    tiers: list[str] = []
    for source in sources:
        if source.name and source.name not in names:
            names.append(source.name)
            tiers.append(source.tier or "")
    if primary_name and primary_name not in names:
        names.append(primary_name)
        tiers.append(event.primary_source.tier or "")
    origin = resolve_originating_source(
        ingest_name=primary_name or None,
        ingest_url=event.primary_source.url if event.primary_source else None,
        article_url=event.article_url,
        publisher_name=event.official_source_name,
    )
    extra_tier = evidence_tier_for_origin(origin, primary_hosts or set())
    if extra_tier and extra_tier not in tiers:
        tiers.append(extra_tier)
    occurred = event.event_time or event.created_at
    return MarketEvent(
        id=str(event.id),
        headline=event.headline or "",
        summary=event.short_summary or "",
        importance=event.importance_score or 0,
        occurred_at=occurred,
        entities=[item for item in (event.entities or []) if isinstance(item, str)],
        event_kind=str(reasoning.get("event_kind") or "other"),
        source_names=names,
        source_tiers=tiers,
        organization_name=organization,
        primary_source_name=primary_name,
        primary_source_tier=(event.primary_source.tier or "") if event.primary_source else "",
        display_source_name=(origin.official_name if origin.used_official else primary_name) or "",
    )


def _linked_sources_by_event(db: Session, event_ids: list) -> dict:
    if not event_ids:
        return {}
    rows = (
        db.query(EventArticle.event_id, Source)
        .join(Article, EventArticle.article_id == Article.id)
        .join(Source, Article.source_id == Source.id)
        .filter(EventArticle.event_id.in_(event_ids))
        .all()
    )
    grouped: dict = {}
    for event_id, source in rows:
        bucket = grouped.setdefault(event_id, [])
        if all(existing.id != source.id for existing in bucket):
            bucket.append(source)
    return grouped


def _in_current_week(query, now: Optional[datetime] = None):
    """Keep events whose real-world time falls in the current ISO week (UTC)."""
    start = current_week_start(now)
    occurred = func.coalesce(Event.event_time, Event.created_at)
    return query.filter(occurred >= start)


def _filtered_page(query, keep, skip: int, limit: int, batch: int = 200) -> list:
    """
    Apply a Python-side filter before pagination, not after it.

    Filtering one SQL page would return short pages and silently drop
    matching rows beyond the first `limit` candidates.
    """
    kept: list = []
    passed = 0
    offset = 0
    while len(kept) < limit:
        rows = query.offset(offset).limit(batch).all()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            if not keep(row):
                continue
            if passed < skip:
                passed += 1
                continue
            kept.append(row)
            if len(kept) == limit:
                break
    return kept


def _in_feed_scope(event: Event) -> bool:
    return is_feed_in_scope(
        event.headline,
        event.short_summary,
        event.primary_source.tier if event.primary_source else None,
    )


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
    player: Optional[str] = Query(None, description="Slug of a major AI organization"),
):
    """
    Retrieve paginated high-signal events.

    Ordered by real-world event_time (fallback created_at), newest first.
    Superseded versions and events with an empty short_summary are excluded.
    Incomplete rows remain addressable by ID on the detail endpoint.
    scope=week limits the feed to the current Monday–Sunday UTC week and
    drops non-AI items from secondary and community sources.
    """
    if player and player not in _PLAYER_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown player")
    query = db.query(Event).options(
        joinedload(Event.primary_source).joinedload(Source.organization)
    ).filter(Event.superseded_by_id.is_(None))
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

    ordered = _order_by_real_world_time(query)
    if scope == "week" or player:
        def keep(event: Event) -> bool:
            if scope == "week" and not _in_feed_scope(event):
                return False
            if player and not event_matches_player(_to_market_event(event, []), player):
                return False
            return True

        events = _filtered_page(ordered, keep, skip, limit)
    else:
        events = ordered.offset(skip).limit(limit).all()

    # Linked articles are omitted from the list view for performance.
    # They are populated in the single-event detail endpoint.
    hosts = _primary_hosts(db)
    linked = _linked_sources_by_event(db, [event.id for event in events])
    responses = []
    for event in events:
        response = _event_response(event, primary_hosts=hosts)
        response.source_count = max(1, len(linked.get(event.id, [])))
        responses.append(response)
    return responses


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
        count = sum(1 for event in rows if _in_feed_scope(event))
        return {"new_events_count": count}
    return {"new_events_count": query.count()}


@router.get("/overview")
def get_market_overview(db: Session = Depends(get_db)):
    """
    Current-week market overview built from canonical events.
    Counts are events. Article copies are not counted again.
    """
    query = (
        db.query(Event)
        .options(joinedload(Event.primary_source).joinedload(Source.organization))
        .filter(Event.superseded_by_id.is_(None))
    )
    query = _high_signal(query)
    query = _in_current_week(query)
    rows = _order_by_real_world_time(query).limit(250).all()
    rows = [event for event in rows if _in_feed_scope(event)]
    links = _linked_sources_by_event(db, [event.id for event in rows])
    primary_hosts = _primary_hosts(db)
    overview = build_market_overview([
        _to_market_event(event, links.get(event.id, []), primary_hosts)
        for event in rows
    ])
    overview["ingestion"] = _ingestion_status(db)
    return overview


def _ingestion_status(db: Session) -> dict:
    """
    Freshness the reader can trust. "Live" is a claim about ingestion,
    not about the newest story, so it comes from the pipeline state.
    """
    last_ingested = (
        db.query(func.max(Event.created_at))
        .filter(Event.superseded_by_id.is_(None))
        .scalar()
    )
    enabled = db.query(Source).filter(Source.enabled.is_(True)).all()
    failing = sum(1 for source in enabled if (source.health_status or "").lower() == "failing")
    from app.core.pipeline import ENRICHMENT_PENDING
    from app.core.scheduler import scheduler

    pending = db.query(func.count(Article.id)).filter(
        Article.enrichment_status == ENRICHMENT_PENDING
    ).scalar() or 0
    return {
        "llm_available": resolve_llm_mode() != LLM_UNAVAILABLE,
        "last_ingested_at": _iso_utc(last_ingested),
        "sources_enabled": len(enabled),
        "sources_failing": failing,
        # Articles fetched and stored but not yet enriched into events.
        "pending_enrichment": int(pending),
        "enrichment_paused": scheduler.enrichment_paused(),
    }


_PLAYER_SLUGS = {slug for slug, _name, _aliases in PLAYERS}
_PLAYER_NAMES = {slug: name for slug, name, _aliases in PLAYERS}
RELATED_WINDOW = timedelta(days=7)


def _naive_utc(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is None or moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _canonical_of(db: Session, event: Event) -> Event:
    """Follow superseded_by_id to the live canonical event (bounded, cycle-safe)."""
    current = event
    seen = {current.id}
    for _ in range(16):
        if current.superseded_by_id is None:
            return current
        nxt = db.query(Event).filter(Event.id == current.superseded_by_id).first()
        if nxt is None or nxt.id in seen:
            return current
        seen.add(nxt.id)
        current = nxt
    return current


def _related_events(db: Session, event: Event, limit: int = 5) -> List[RelatedEventResponse]:
    """
    Other live developments near this one that share an attributed
    organization, or share a named entity within the same category.
    A shared generic word is not a relationship.
    """
    anchor = _naive_utc(event.event_time or event.created_at)
    if anchor is None:
        return []
    when = func.coalesce(Event.event_time, Event.created_at)
    candidates = _high_signal(
        db.query(Event)
        .options(joinedload(Event.primary_source).joinedload(Source.organization))
        .filter(
            Event.superseded_by_id.is_(None),
            Event.id != event.id,
            when >= anchor - RELATED_WINDOW,
            when <= anchor + RELATED_WINDOW,
        )
    ).limit(300).all()
    base = _to_market_event(event, [])
    base_players = {slug for slug, _name in matching_players(base)}
    base_category = market_category(base)
    base_entities = {item.strip().lower() for item in base.entities if len(item.strip()) > 2}
    base_headline = (event.headline or "").strip().lower()
    scored = []
    for candidate in candidates:
        if not _in_feed_scope(candidate):
            continue
        if (candidate.headline or "").strip().lower() == base_headline:
            continue
        other = _to_market_event(candidate, [])
        shared_players = base_players & {slug for slug, _name in matching_players(other)}
        category = market_category(other) or ""
        shared_entities = base_entities & {
            item.strip().lower() for item in other.entities if len(item.strip()) > 2
        }
        if shared_players:
            reason = ", ".join(sorted(_PLAYER_NAMES[slug] for slug in shared_players))
        elif shared_entities and base_category and category == base_category:
            reason = category
        else:
            continue
        other_time = _naive_utc(candidate.event_time or candidate.created_at)
        distance = abs((other_time - anchor).total_seconds()) if other_time else float("inf")
        scored.append((
            (-len(shared_players), -len(shared_entities), distance),
            RelatedEventResponse(
                id=str(candidate.id),
                headline=candidate.headline,
                event_time=candidate.event_time or candidate.created_at,
                category=category,
                reason=reason,
            ),
        ))
    scored.sort(key=lambda item: item[0])
    return [item[1] for item in scored[:limit]]


def _current_evidence(db: Session, event: Event) -> List[str]:
    """
    Stored citations that still pass today's evidence validator against the
    primary article. Citations stored before the claim-support rule existed
    are real source text but can be unrelated to the card's claim; "Quoted
    from the source" must not present them as support.
    """
    from app.core.deduplication import validate_evidence

    article = (
        db.query(Article)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .filter(EventArticle.event_id == event.id, EventArticle.link_type == "primary")
        .first()
    )
    stored = [item for item in (event.citations or []) if isinstance(item, str)]
    if article is None or not stored:
        return present_citations(stored)
    claim = " ".join(part for part in (event.headline, event.short_summary, event.what_changed) if part)
    source = f"{article.title}\n\n{article.raw_content or ''}"
    return present_citations(validate_evidence(source, stored, claim=claim))


def _page_url(url: Optional[str]) -> str:
    return (url or "").split("#update-")[0]


def _previous_versions(db: Session, event: Event, limit: int = 10) -> List[PreviousVersionResponse]:
    """
    Earlier versions of the same source page. A version chain shares the
    page URL; a merged duplicate from another publisher does not, and is
    evidence, not a version.
    """
    page = _page_url(event.article_url)
    reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
    if not page or (event.version or 1) <= 1 or "churn_created_at" in reasoning:
        return []
    out: List[PreviousVersionResponse] = []
    current = event
    seen = {event.id}
    while len(out) < limit:
        prior = (
            db.query(Event)
            .filter(Event.superseded_by_id == current.id)
            .order_by(Event.version.desc())
            .all()
        )
        prior = [row for row in prior if row.id not in seen and _page_url(row.article_url) == page]
        if not prior:
            break
        current = prior[0]
        seen.add(current.id)
        out.append(PreviousVersionResponse(
            id=str(current.id),
            version=current.version or 1,
            headline=current.headline or "",
            recorded_at=current.created_at,
        ))
    return out


@router.get("/{event_id}/resolve")
def resolve_event(event_id: str, db: Session = Depends(get_db)):
    """
    Cheap existence check for the frontend proxy, run before a page streams
    so a missing event can return a real 404 and a merged duplicate a real
    redirect. One indexed lookup plus the supersession chain.
    """
    try:
        event_uuid = uuid_module.UUID(event_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Event not found")
    event = db.query(Event).filter(Event.id == event_uuid).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    canonical = _canonical_of(db, event) if event.superseded_by_id is not None else event
    return {"id": str(event.id), "canonical_id": str(canonical.id)}


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

    response = _event_response(
        event,
        linked_articles=_build_linked_articles(db, event.id),
        include_reasoning=True,
        primary_hosts=_primary_hosts(db),
    )
    if event.superseded_by_id is not None:
        # A merged duplicate keeps its id so old links resolve, but its
        # articles now live on the canonical event. Point the client there.
        canonical = _canonical_of(db, event)
        response.superseded_by_id = str(event.superseded_by_id)
        response.canonical_id = str(canonical.id)
    else:
        response.canonical_id = str(event.id)
        response.related = _related_events(db, event)
        response.previous_versions = _previous_versions(db, event)
        response.citations = _current_evidence(db, event)
    response.source_count = max(
        1, len({article.source_name for article in response.linked_articles if article.source_name})
    )
    return response
