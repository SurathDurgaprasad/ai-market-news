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


def _category_event(event: Event):
    """The fields market_category reads, from a stored event."""
    from app.core.market import MarketEvent

    reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
    return MarketEvent(
        id=str(event.id),
        headline=event.headline or "",
        summary=event.short_summary or "",
        importance=event.importance_score or 0,
        occurred_at=event.event_time or event.created_at or datetime.now(timezone.utc),
        event_kind=str(reasoning.get("event_kind") or "other"),
        classified_category=str(reasoning.get("market_category") or ""),
    )


# Historical category backfill: card text only, batched, two passes.
CATEGORY_BATCH_SIZE = 20
CATEGORY_CARD_CHARS = 320
# System prompt plus JSON schema, per request (measured ~420 tokens for gpt-4.1).
_CATEGORY_REQUEST_OVERHEAD_TOKENS = 450
_CATEGORY_OUTPUT_TOKENS_PER_CARD = 14
_CATEGORY_SECONDS_PER_REQUEST = 6


def category_backfill_candidates(db: Session, limit: int = 1000) -> list[Event]:
    """Live events with no category from any rule and no stored market_category answer."""
    from app.core.market import market_category

    live = (
        db.query(Event)
        .filter(Event.superseded_by_id.is_(None))
        .order_by(func.coalesce(Event.event_time, Event.created_at).desc())
        .all()
    )
    found: list[Event] = []
    for event in live:
        reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
        if "market_category" in reasoning or not (event.headline or "").strip():
            continue
        if market_category(_category_event(event)):
            continue
        found.append(event)
        if len(found) >= limit:
            break
    return found


def _category_card(event: Event) -> str:
    summary = " ".join((event.short_summary or "").split())[:CATEGORY_CARD_CHARS]
    return f"{event.headline}. {summary}".strip()


def estimate_category_backfill(events: list[Event], batch_size: int = CATEGORY_BATCH_SIZE) -> dict:
    """Requests, tokens and runtime for two batched passes, before any call is made."""
    batches = -(-len(events) // batch_size) if events else 0
    card_tokens = sum(len(_category_card(event)) // 4 + 12 for event in events)
    requests = 2 * batches
    return {
        "events": len(events),
        "batch_size": batch_size,
        "requests": requests,
        "input_tokens": 2 * card_tokens + requests * _CATEGORY_REQUEST_OVERHEAD_TOKENS,
        "output_tokens": 2 * len(events) * _CATEGORY_OUTPUT_TOKENS_PER_CARD,
        "runtime_seconds": requests * _CATEGORY_SECONDS_PER_REQUEST,
    }


def _classify_batch(llm, cards: list[tuple[str, str]], pause_seconds: float) -> dict:
    """
    One batch, retried once after a pause (rate limits). Raises
    LlmUnavailableError after that, and ProviderQuotaExhausted at once.
    """
    import time

    from app.core.llm_usage import llm_subject
    from app.core.providers.llm import LlmUnavailableError, ProviderQuotaExhausted

    with llm_subject(f"category_backfill:{cards[0][0]}..{cards[-1][0]}"):
        for attempt in range(2):
            try:
                answers = llm.classify_categories(cards)
                if pause_seconds:
                    time.sleep(pause_seconds)
                return answers
            except ProviderQuotaExhausted:
                raise  # no quota: every further request would fail too
            except LlmUnavailableError:
                if attempt == 1:
                    raise
                time.sleep(max(pause_seconds, 20.0))
    return {}


def classify_categories_batched(
    llm,
    events: list[Event],
    *,
    batch_size: int = CATEGORY_BATCH_SIZE,
    pause_seconds: float = 0.0,
) -> list[dict]:
    """
    Two independent batched passes over card text. Pass B sees the cards in
    reverse order, so each card is judged next to different neighbours. A
    label is proposed only when both passes return the same taxonomy label,
    and never Security (that still needs security language). No database
    writes; the result is applied separately.
    """
    from app.core.market import normalize_market_category

    ids = {f"c{index + 1}": event for index, event in enumerate(events)}
    order = list(ids.items())

    def run(pass_order):
        answers: dict[str, Optional[str]] = {}
        for start in range(0, len(pass_order), batch_size):
            chunk = pass_order[start:start + batch_size]
            cards = [(card_id, _category_card(event)) for card_id, event in chunk]
            answers.update(_classify_batch(llm, cards, pause_seconds))
        return answers

    first = run(order)
    second = run(list(reversed(order)))
    rows = []
    for card_id, event in order:
        a = normalize_market_category(first.get(card_id))
        b = normalize_market_category(second.get(card_id))
        label = a if a and a == b and a != "Security" else None
        rows.append({"event_id": str(event.id), "headline": event.headline, "pass_a": a, "pass_b": b, "label": label})
    return rows


def apply_category_backfill(db: Session, rows: list[dict]) -> int:
    """
    Store agreed labels from a saved dry run. No LLM call. Each event is
    re-checked: still live, still uncategorized, no stored answer. Reverted
    by removing market_category and category_backfill from importance_reasoning.
    """
    import uuid

    from app.core.market import MARKET_CATEGORIES, market_category

    applied = 0
    for row in rows:
        label = row.get("label")
        if label not in MARKET_CATEGORIES or label == "Security":
            continue
        try:
            event = db.get(Event, uuid.UUID(str(row.get("event_id"))))
        except ValueError:
            continue
        if event is None or event.superseded_by_id is not None:
            continue
        reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
        if "market_category" in reasoning or market_category(_category_event(event)):
            continue
        updated = dict(reasoning)
        updated["market_category"] = label
        updated["category_backfill"] = {
            "method": "batched_card_two_pass",
            "pass_a": row.get("pass_a"),
            "pass_b": row.get("pass_b"),
        }
        event.importance_reasoning = updated
        applied += 1
    db.commit()
    return applied


def revert_category_backfill(db: Session) -> int:
    reverted = 0
    for event in db.query(Event).all():
        reasoning = event.importance_reasoning if isinstance(event.importance_reasoning, dict) else {}
        if "category_backfill" not in reasoning:
            continue
        updated = {k: v for k, v in reasoning.items() if k not in ("market_category", "category_backfill")}
        event.importance_reasoning = updated
        reverted += 1
    db.commit()
    return reverted


def repair_digest_events(db: Session, llm, *, apply: bool = False) -> list[tuple[str, list, list, str]]:
    """
    Newsletter-digest cards classified from the whole digest before the
    lead-segment boundary existed. A card is repaired only when its stored
    entities include a name the digest's roundup section contains and its
    lead story does not (the must-reads' names), and only when the headline
    itself is about the lead story. Such a card is classified again from the
    lead segment, as ingestion now does; the old entities, kind and
    importance are kept in importance_reasoning["digest_repair"]. A card
    whose headline came from the roundup is reported, not changed: fixing it
    means a new summary, not new entities.
    Returns (headline, old, new, status) with status "repaired" or
    "headline from roundup".
    """
    from app.core.digest import entities_named_in, is_digest, lead_segment
    from app.core.importance import calibrate_importance_score, normalize_importance_score
    from app.core.market import normalize_market_category

    from app.core.deduplication import claim_stems

    repaired: list[tuple[str, list, list, str]] = []
    for event in db.query(Event).filter(Event.superseded_by_id.is_(None)).all():
        article = _primary_article(db, event)
        if article is None or not is_digest(article.title, article.raw_content):
            continue
        lead = lead_segment(article.title, article.raw_content)
        roundup = (article.raw_content or "")[len(lead):]
        old = [e for e in (event.entities or []) if isinstance(e, str)]
        in_lead = set(entities_named_in(old, lead))
        leaked = [e for e in entities_named_in(old, roundup) if e not in in_lead]
        if not leaked:
            continue  # nothing came in from another story
        headline_stems = claim_stems(event.headline)
        if len(headline_stems & claim_stems(lead)) <= len(headline_stems & claim_stems(roundup)):
            repaired.append((event.headline, old, old, "headline from roundup"))
            continue
        result = llm.classify_event(lead)
        if result is None:
            continue
        new = entities_named_in(list(result.primary_entities or result.entities or []), lead)
        repaired.append((event.headline, old, new, "repaired"))
        if not apply:
            continue
        reasoning = dict(event.importance_reasoning) if isinstance(event.importance_reasoning, dict) else {}
        score = normalize_importance_score(result.importance_score)
        kind = result.event_kind or "other"
        reasoning["digest_repair"] = {
            "entities": old,
            "mentioned_entities": list(event.mentioned_entities or []),
            "event_kind": reasoning.get("event_kind"),
            "importance_score": event.importance_score,
        }
        reasoning.update(
            event_kind=kind,
            scope=result.technical_change_scope,
            security_impact=result.security_impact,
            market_category=normalize_market_category(result.market_category),
        )
        event.entities = new
        event.mentioned_entities = entities_named_in(list(result.mentioned_entities or []), lead)
        if score is not None:
            event.importance_score = calibrate_importance_score(
                score, kind, result.technical_change_scope, result.security_impact
            ) or event.importance_score
        event.importance_reasoning = reasoning
    if apply and any(status == "repaired" for *_rest, status in repaired):
        db.commit()
    return repaired


def propose_digest_rebuild(db: Session, llm, event_id: str) -> dict:
    """
    A digest card whose headline, summary and citations all came from a
    roundup item (repair-digests reports it as "headline from roundup").
    The card is rebuilt from the digest's lead story, the same way ingestion
    now builds one: summary and classification from the lead segment,
    citations kept only when the evidence validator finds them in it. Two
    LLM requests. Nothing is written; apply_digest_rebuild stores it.
    Returns {"status": ..., "event_id", "old", "new"}.
    """
    import uuid

    from app.core.deduplication import fallback_source_citations, validate_evidence
    from app.core.digest import entities_named_in, is_digest, lead_segment
    from app.core.entities import select_primary_entities
    from app.core.importance import calibrate_importance_score, normalize_importance_score
    from app.core.llm_usage import llm_subject
    from app.core.market import normalize_market_category

    event = db.get(Event, uuid.UUID(str(event_id)))
    if event is None or event.superseded_by_id is not None:
        return {"status": "not a live event", "event_id": str(event_id)}
    article = _primary_article(db, event)
    if article is None or not is_digest(article.title, article.raw_content):
        return {"status": "not a newsletter digest", "event_id": str(event_id)}
    lead = lead_segment(article.title, article.raw_content)
    if lead == (article.raw_content or ""):
        return {"status": "no lead-story boundary", "event_id": str(event_id)}
    with llm_subject(f"event:{event.id}"):
        classification = llm.classify_event(lead)
        summary = llm.summarize_event(lead)
    if summary is None or not (summary.headline or "").strip() or classification is None:
        return {"status": "model returned no usable summary", "event_id": str(event_id)}
    claim = " ".join(part for part in (summary.headline, summary.short_summary, summary.what_changed) if part)
    citations = validate_evidence(lead, summary.citations or [], claim=claim) or fallback_source_citations(
        lead, short_summary=summary.short_summary, what_changed=summary.what_changed
    )
    if not citations:
        return {"status": "no evidence found in the lead story", "event_id": str(event_id)}
    primary, mentioned = select_primary_entities(
        primary=classification.primary_entities,
        mentioned=classification.mentioned_entities,
        all_entities=classification.entities,
        headline=summary.headline,
        summary=summary.short_summary,
    )
    kind = classification.event_kind or "other"
    score = normalize_importance_score(classification.importance_score)
    if score is not None:
        score = calibrate_importance_score(score, kind, classification.technical_change_scope, classification.security_impact)
    duplicate = (
        db.query(Event)
        .filter(Event.superseded_by_id.is_(None), Event.id != event.id, Event.headline == summary.headline.strip())
        .first()
    )
    if duplicate is not None:
        return {"status": "headline already used by another live card", "event_id": str(event_id)}
    return {
        "status": "proposed",
        "event_id": str(event.id),
        "old": {
            "headline": event.headline,
            "short_summary": event.short_summary,
            "what_changed": event.what_changed,
            "citations": list(event.citations or []),
            "entities": list(event.entities or []),
            "mentioned_entities": list(event.mentioned_entities or []),
            "importance_score": event.importance_score,
            "importance_reasoning": event.importance_reasoning,
        },
        "new": {
            "headline": summary.headline.strip(),
            "short_summary": (summary.short_summary or "").strip(),
            "what_changed": summary.what_changed,
            "citations": citations,
            "entities": entities_named_in(primary, lead),
            "mentioned_entities": entities_named_in(mentioned, lead),
            "importance_score": score or event.importance_score,
            "event_kind": kind,
            "scope": classification.technical_change_scope,
            "security_impact": classification.security_impact,
            "market_category": normalize_market_category(classification.market_category),
            "importance_text": classification.importance_reasoning,
        },
    }


def apply_digest_rebuild(db: Session, proposal: dict) -> str:
    """
    Store a saved proposal. No LLM call. Evidence is checked again against
    the stored lead story, and the old card is kept in
    importance_reasoning["digest_rebuild"] so the change can be reverted.
    """
    import uuid

    from app.core.deduplication import _normalize_citation_text
    from app.core.digest import lead_segment

    if proposal.get("status") != "proposed":
        return "nothing to apply"
    event = db.get(Event, uuid.UUID(str(proposal["event_id"])))
    if event is None or event.superseded_by_id is not None:
        return "not a live event"
    if event.headline != proposal["old"]["headline"]:
        return "card changed since the proposal"
    article = _primary_article(db, event)
    lead = lead_segment(article.title, article.raw_content) if article is not None else ""
    new = proposal["new"]
    source = _normalize_citation_text(lead)
    if not new["citations"] or any(_normalize_citation_text(c) not in source for c in new["citations"]):
        return "evidence is not in the lead story"
    event.headline = new["headline"]
    event.short_summary = new["short_summary"]
    event.what_changed = new["what_changed"]
    event.citations = new["citations"]
    event.entities = new["entities"]
    event.mentioned_entities = new["mentioned_entities"]
    event.importance_score = new["importance_score"]
    event.importance_reasoning = {
        "text": new["importance_text"],
        "event_kind": new["event_kind"],
        "scope": new["scope"],
        "security_impact": new["security_impact"],
        "market_category": new["market_category"],
        "digest_rebuild": proposal["old"],
    }
    db.commit()
    return "applied"
