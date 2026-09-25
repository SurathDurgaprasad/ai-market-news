"""
Attach safely-matched duplicate cards onto one canonical event.

Uses the same title predicates as ingestion. Does not call an LLM and does
not merge events the predicates reject (different products, contrasting claims).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

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
    Keep the card that names the product, then the one whose headline says
    who acted, then the higher source tier.

    A community post whose headline names the model beats a generic
    secondary headline about the same release, because the named card is
    the one readers should open. Two named cards still prefer primary.
    "Meta announces Muse Charm" beats "Tiny device provides a home for Muse".
    """
    named = 0 if named_product_keys(event.headline) else 1
    actor = 0 if _headline_names_actor(event) else 1
    tier = ""
    if event.primary_source is not None and event.primary_source.tier:
        tier = event.primary_source.tier.lower()
    when = event.event_time or event.created_at or datetime.max.replace(tzinfo=timezone.utc)
    return (named, actor, _TIER_RANK.get(tier, 2), -(event.importance_score or 0), when)


def _headline_names_actor(event: Event) -> bool:
    from app.core.market import _players_in

    headline = event.headline or ""
    if _players_in([headline]):
        return True
    lowered = headline.lower()
    entities = [e for e in (event.entities or []) if isinstance(e, str) and e.strip()]
    # The first extracted entity is the subject; a product alone is not the actor.
    return bool(entities) and len(entities) > 1 and entities[0].lower() in lowered


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


def repair_churn_versions(
    db: Session,
    *,
    apply: bool = False,
    refetch: Optional[Callable[[str], Optional[str]]] = None,
) -> list[tuple[str, int]]:
    """
    Live versions created only because a page's counters or relative times
    changed (before is_immaterial_change existed) are not new developments.
    Their created_at is restored to when the development was first recorded,
    so freshness and "new" counts are not inflated. The version itself,
    its evidence and its headline are kept. With apply, the replaced
    created_at is kept in importance_reasoning["churn_created_at"].
    Returns (headline, version) for each repaired event.

    With refetch (page URL -> text from today's extractor), a chain whose
    stored texts differ is also checked against the live page: when the
    first recorded text and today's differ only immaterially, the versions
    in between came from page chrome (a rotating promo block, leaked
    comment JSON), not from an edit of the article.
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
        root = chain[-1]
        if not is_immaterial_change(before.raw_content, mine.raw_content):
            original = _primary_article(db, root) if refetch else None
            fresh = refetch((event.article_url or "").split("#update-")[0]) if original else None
            if not fresh or not is_immaterial_change(original.raw_content, fresh):
                continue
        # Earliest record of the development, skipping churn-only steps.
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


RECHECK_WINDOW = timedelta(days=7)
RECHECK_PAIR_GAP = timedelta(hours=48)


def _entity_overlap(left: Event, right: Event) -> bool:
    """The pipeline's candidate rule: a shared entity, or one named inside the other."""
    import re

    def names(event: Event) -> list[str]:
        return [e.lower() for e in (event.entities or []) if isinstance(e, str) and e.strip()]

    mine, theirs = names(left), names(right)
    text = f"{right.headline or ''} {right.short_summary or ''}".lower()
    for entity in mine:
        if entity in text or entity in theirs:
            return True
        if any(len(other) >= 4 and re.search(rf"\b{re.escape(other)}\b", entity) for other in theirs):
            return True
    return False


def recheck_recent_duplicates(
    db: Session,
    llm,
    *,
    apply: bool = False,
    max_checks: int = 60,
    now: datetime | None = None,
) -> list[tuple[str, str]]:
    """
    Ask the relationship model about recent live events that ingestion never
    compared (their entities did not overlap under the older rule, or they
    were created while another provider was active). Pairs are filtered
    exactly like ingestion candidates: published within 48 hours of each
    other, overlapping entities, compatible event kinds; most similar
    first. The model compares the two cards (headline and summary), not raw
    article text: a newsletter roundup mentions several stories and would
    otherwise match each of them. Only SAME_EVENT merges. Returns
    (kept headline, merged headline) pairs.
    """
    from app.core.deduplication import claim_stems
    from app.core.importance import kinds_are_compatible

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = (moment - RECHECK_WINDOW).astimezone(timezone.utc).replace(tzinfo=None)
    events = (
        db.query(Event)
        .options(joinedload(Event.primary_source))
        .filter(Event.superseded_by_id.is_(None))
        .filter(func.coalesce(Event.event_time, Event.created_at) >= cutoff)
        .all()
    )

    def when(event: Event) -> datetime:
        stamp = event.event_time or event.created_at
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp

    pairs = []
    for i, left in enumerate(events):
        for right in events[i + 1:]:
            if abs(when(left) - when(right)) > RECHECK_PAIR_GAP:
                continue
            if not kinds_are_compatible(_event_kind(left), _event_kind(right)):
                continue
            newer, older = (left, right) if when(left) >= when(right) else (right, left)
            if _entity_overlap(newer, older):
                shared = claim_stems(f"{newer.headline} {newer.short_summary}") & claim_stems(
                    f"{older.headline} {older.short_summary}"
                )
                pairs.append((len(shared), newer, older))
    pairs.sort(key=lambda item: item[0], reverse=True)

    merged: list[tuple[str, str]] = []
    gone: set = set()
    for _shared, newer, older in pairs[:max_checks]:
        if newer.id in gone or older.id in gone:
            continue
        incoming = "\n".join(part for part in (newer.headline, newer.short_summary, newer.what_changed) if part)
        existing = "\n".join(part for part in (older.headline, older.short_summary) if part)
        result = llm.classify_relationship(incoming, existing)
        if not result.is_merge():
            continue
        canonical, duplicate = sorted((newer, older), key=_prefer)
        merged.append((canonical.headline, duplicate.headline))
        gone.add(duplicate.id)
        if apply:
            _move_articles(db, duplicate, canonical)
            duplicate.superseded_by_id = canonical.id
    if apply and merged:
        db.commit()
    return merged


def restore_version_evidence(db: Session, *, apply: bool = False, llm=None) -> list[tuple[str, int]]:
    """
    Evidence left on superseded versions. Until 2026-09-25 a new version
    linked only the edited page, so other reports merged into the card
    stayed on the old version and disappeared from the live card. Copies
    each such article onto the live card as supporting evidence; the edited
    page's own earlier text stays with its version. With llm, a page is
    restored only when the relationship model calls it the same development
    as the live card: some of those old merges were related work, not the
    same development. Returns (headline, number of restored articles) per
    live event.
    """
    from app.models.article import Article

    restored: list[tuple[str, int]] = []
    live = db.query(Event).filter(Event.superseded_by_id.is_(None), Event.version > 1).all()
    for event in live:
        page = (event.article_url or "").split("#update-")[0]
        have = {
            article_id for (article_id,) in
            db.query(EventArticle.article_id).filter(EventArticle.event_id == event.id).all()
        }
        found: dict = {}
        frontier, seen = [event.id], {event.id}
        while frontier and len(seen) < 200:
            current = frontier.pop()
            for (prior_id,) in db.query(Event.id).filter(Event.superseded_by_id == current).all():
                if prior_id in seen:
                    continue
                seen.add(prior_id)
                frontier.append(prior_id)
                rows = (
                    db.query(EventArticle, Article)
                    .join(Article, EventArticle.article_id == Article.id)
                    .filter(EventArticle.event_id == prior_id)
                    .all()
                )
                for link, article in rows:
                    if article.id in have or (article.url or "").split("#update-")[0] == page:
                        continue
                    found.setdefault(article.id, link.similarity_score)
        if found and llm is not None:
            card = "\n".join(part for part in (event.headline, event.short_summary) if part)
            verdicts: dict = {}
            for article in db.query(Article).filter(Article.id.in_(list(found))).all():
                page_of = (article.url or "").split("#update-")[0]
                if page_of not in verdicts:
                    text = f"{article.title}\n\n{(article.raw_content or '')[:2000]}"
                    verdicts[page_of] = llm.classify_relationship(text, card).is_merge()
                if not verdicts[page_of]:
                    found.pop(article.id, None)
        if not found:
            continue
        restored.append((event.headline, len(found)))
        if apply:
            for article_id, score in found.items():
                db.add(EventArticle(event_id=event.id, article_id=article_id,
                                    link_type="supporting", similarity_score=score))
    if apply and restored:
        db.commit()
    return restored
