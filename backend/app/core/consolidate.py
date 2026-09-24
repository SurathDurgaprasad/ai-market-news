"""
Attach safely-matched duplicate cards onto one canonical event.

Uses the same title predicates as ingestion. Does not call an LLM and does
not merge events the predicates reject (different products, contrasting claims).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.deduplication import (
    classify_headline_relationship,
    coverage_of_same_named_release,
    named_product_keys,
    titles_are_safe_lexical_match,
    titles_are_same_outlet_paraphrase,
    titles_are_same_release_wording,
)
from app.core.providers.llm import EventRelationship
from app.models.event import Event, EventArticle

_TIER_RANK = {"primary": 0, "research": 1, "secondary": 2, "community": 3}

# Pairwise comparison is quadratic, so only recent events are compared.
# Coverage of one development is published within days, not weeks; older
# canonical events are already settled and are not re-examined every cycle.
CONSOLIDATION_WINDOW = timedelta(days=14)


def _event_kind(event: Event) -> str:
    reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
    return str(reasoning.get("event_kind") or "")


def _close_in_time(left: Event, right: Event) -> bool:
    """Paraphrases of one story are published together, not months apart."""
    left_time = left.event_time or left.created_at
    right_time = right.event_time or right.created_at
    if left_time is None or right_time is None:
        return False
    if left_time.tzinfo is None:
        left_time = left_time.replace(tzinfo=timezone.utc)
    if right_time.tzinfo is None:
        right_time = right_time.replace(tzinfo=timezone.utc)
    return abs(left_time - right_time) <= timedelta(hours=48)


def _should_merge(left: Event, right: Event) -> bool:
    """
    One canonical card when the headlines are the same real-world development.

    A later distribution stays a separate event. Same organization, product,
    or topic is not enough.
    """
    relationship = classify_headline_relationship(
        left.headline or "",
        right.headline or "",
        _event_kind(left),
        _event_kind(right),
    )
    if relationship == EventRelationship.SAME_EVENT:
        headline_a = left.headline or ""
        headline_b = right.headline or ""
        if titles_are_safe_lexical_match(headline_a, headline_b) or titles_are_same_release_wording(
            headline_a, headline_b
        ):
            return True
        return _close_in_time(left, right)
    if coverage_of_same_named_release(
        left.headline or "",
        left.article_url,
        right.headline or "",
        right.article_url,
    ):
        return True
    same_source = (
        left.primary_source_id is not None
        and left.primary_source_id == right.primary_source_id
    )
    return bool(same_source and titles_are_same_outlet_paraphrase(left.headline or "", right.headline or ""))


def _prefer(event: Event):
    """
    Keep the card that names the product, then the higher source tier.

    A community post whose headline names the model beats a generic
    secondary headline about the same release, because the named card is
    the one readers should open. Two named cards still prefer primary.
    """
    named = 0 if named_product_keys(event.headline) else 1
    tier = ""
    if event.primary_source is not None and event.primary_source.tier:
        tier = event.primary_source.tier.lower()
    when = event.event_time or event.created_at or datetime.max.replace(tzinfo=timezone.utc)
    return (named, _TIER_RANK.get(tier, 2), -(event.importance_score or 0), when)


def _move_articles(db: Session, duplicate: Event, canonical: Event) -> None:
    links = (
        db.query(EventArticle)
        .filter(EventArticle.event_id == duplicate.id)
        .all()
    )
    pending = [(link.article_id, link.similarity_score) for link in links]
    for link in links:
        db.delete(link)
    db.flush()
    for article_id, score in pending:
        exists = (
            db.query(EventArticle)
            .filter(
                EventArticle.event_id == canonical.id,
                EventArticle.article_id == article_id,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            EventArticle(
                event_id=canonical.id,
                article_id=article_id,
                link_type="supporting",
                similarity_score=score,
            )
        )


def consolidate_safe_duplicates(db: Session, now: datetime | None = None) -> int:
    """
    Merge live events that the lexical predicates already treat as one story.

    Only events inside CONSOLIDATION_WINDOW are compared.
    Returns the number of duplicate events superseded.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = (moment - CONSOLIDATION_WINDOW).astimezone(timezone.utc).replace(tzinfo=None)
    events = (
        db.query(Event)
        .options(joinedload(Event.primary_source))
        .filter(Event.superseded_by_id.is_(None))
        .filter(func.coalesce(Event.event_time, Event.created_at) >= cutoff)
        .all()
    )
    parent = {event.id: event.id for event in events}

    def find(item):
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    for i, left in enumerate(events):
        for right in events[i + 1 :]:
            if _should_merge(left, right):
                union(left.id, right.id)

    clusters: dict = {}
    for event in events:
        clusters.setdefault(find(event.id), []).append(event)

    merged = 0
    for group in clusters.values():
        if len(group) < 2:
            continue
        canonical = min(group, key=_prefer)
        for duplicate in group:
            if duplicate.id == canonical.id:
                continue
            _move_articles(db, duplicate, canonical)
            duplicate.superseded_by_id = canonical.id
            merged += 1
    if merged:
        db.commit()
    return merged


def _primary_article(db: Session, event: Event):
    from app.models.article import Article

    return (
        db.query(Article)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .filter(EventArticle.event_id == event.id, EventArticle.link_type == "primary")
        .first()
    )


def repair_churn_versions(db: Session, *, apply: bool = False) -> list[tuple[str, int]]:
    """
    Live versions created only because a page's counters or relative times
    changed (before is_immaterial_change existed) are not new developments.
    Their created_at is restored to when the development was first recorded,
    so freshness and "new" counts are not inflated. The version itself,
    its evidence and its headline are kept. With apply, the replaced
    created_at is kept in importance_reasoning["churn_created_at"].
    Returns (headline, version) for each repaired event.
    """
    from app.core.deduplication import is_immaterial_change

    repaired: list[tuple[str, int]] = []
    live = db.query(Event).filter(Event.superseded_by_id.is_(None), Event.version > 1).all()
    for event in live:
        chain = []
        current = event
        for _ in range(50):
            previous = (
                db.query(Event)
                .filter(Event.superseded_by_id == current.id)
                .order_by(Event.version.desc())
                .first()
            )
            if previous is None:
                break
            chain.append(previous)
            current = previous
        if not chain:
            continue
        mine, before = _primary_article(db, event), _primary_article(db, chain[0])
        if mine is None or before is None:
            continue
        if not is_immaterial_change(before.raw_content, mine.raw_content):
            continue
        # Earliest record of the development, skipping churn-only steps.
        root = chain[-1]
        if event.created_at is None or root.created_at is None or event.created_at <= root.created_at:
            continue
        repaired.append((event.headline, event.version))
        if apply:
            reasoning = dict(event.importance_reasoning) if isinstance(event.importance_reasoning, dict) else {}
            reasoning.setdefault("churn_created_at", event.created_at.isoformat())
            event.importance_reasoning = reasoning
            event.created_at = root.created_at
    if apply and repaired:
        db.commit()
    return repaired
