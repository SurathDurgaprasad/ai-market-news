from typing import Optional, Callable
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging

from app.models.article import Article
from app.models.event import Event
from app.core.providers.llm import get_llm_provider, LlmUnavailableError, resolve_llm_mode
from app.core.runtime import is_test_runtime
from app.core.deduplication import (
    normalize_url,
    generate_content_hash,
    verify_citations,
    fallback_source_citations,
    titles_are_safe_lexical_match,
    titles_are_same_outlet_paraphrase,
    titles_are_same_release_wording,
    title_versioned_entities,
    first_factual_line,
    first_source_excerpt,
)
from app.core.urls import sanitize_http_url
from app.core.importance import (
    is_obvious_noise,
    normalize_importance_score,
    calibrate_importance_score,
    infer_event_signals,
    kinds_are_compatible,
)
from app.core.entities import select_primary_entities
from app.core.origin import resolve_originating_source
from app.core.article_body import enrich_article, MIN_CONTENT_CHARS

logger = logging.getLogger(__name__)

class IntelligencePipeline:
    def __init__(self, db: Session, llm_env: Optional[str] = None):
        self.db = db
        self.llm_mode = resolve_llm_mode(llm_env)
        self.llm = get_llm_provider(env=llm_env)
        logger.info("pipeline llm=%s mode=%s", type(self.llm).__name__, self.llm_mode)
        self.last_outcome: Optional[str] = None

    def _release_db(self) -> None:
        """End the current transaction so SQLite is not held across NVIDIA/LLM calls."""
        try:
            if self.db.in_transaction():
                self.db.commit()
        except Exception:
            self.db.rollback()

    def process_article(
        self,
        article_data: 'ArticleData',
        source_id: str,
        fetch_fn: Optional[Callable] = None,
    ) -> Optional[Event]:
        """
        Runs the full ingestion pipeline for a single article.
        Returns the canonical Event this article was clustered into.
        last_outcome is one of: created, linked, duplicate, rejected, llm_unavailable.
        """
        from app.models.event import EventArticle

        self.last_outcome = "rejected"

        if article_data is None:
            return None

        # 1. Normalize
        url = normalize_url(article_data.url)
        title = article_data.title
        content = article_data.content or ""

        if not url or not title:
            logger.debug(f"REJECT [missing url or title]: url={article_data.url!r}")
            return None

        if is_obvious_noise(title, content):
            logger.info(f"REJECT [deterministic noise]: {url}")
            return None

        if fetch_fn is None and not is_test_runtime():
            from app.core.fetcher import fetch_url
            fetch_fn = fetch_url

        content, image_url, publisher_name = enrich_article(
            title, url, content, article_data.image_url, fetch_fn=fetch_fn
        )

        # 2. Validate minimum content length
        stripped_content = content.strip()
        if len(stripped_content) < MIN_CONTENT_CHARS:
            logger.debug(f"REJECT [content too short ({len(stripped_content)} chars)]: {url}")
            return None
        content = stripped_content
            
        # 3. Deduplicate - Exact URL or Exact Content Hash
        content_hash = generate_content_hash(content)
        existing_article_by_url = self.db.query(Article).filter(Article.url == url).first()
        
        is_same_url_update = False
        original_event_id_to_supersede = None
        
        if existing_article_by_url:
            if existing_article_by_url.hash == content_hash:
                logger.debug(f"SKIP [exact duplicate, hash unchanged]: {url}")
                self.last_outcome = "duplicate"
                return None  # Exact duplicate, nothing changed
            else:
                # The content at this URL has changed — ingest as an update
                # and flag it to supersede the original event.
                logger.info(f"UPDATE [same URL, content changed]: {url}")
                is_same_url_update = True
                url = f"{url}#update-{content_hash[:8]}"

                # Find the MOST RECENT live event for this base URL. Following the
                # supersession chain is critical when the RSS feed publishes multiple
                # update snippets in the same batch: each strips to the same base URL,
                # finds the same original article, and without chaining would all try
                # to supersede the same original event — leaving orphan update events.
                from app.models.event import EventArticle
                link = self.db.query(EventArticle).filter(EventArticle.article_id == existing_article_by_url.id).first()
                if link:
                    original_event_id_to_supersede = link.event_id
                    # Follow the supersession chain to the current live version.
                    candidate = self.db.query(Event).filter(Event.id == original_event_id_to_supersede).first()
                    candidate = self._live_event(candidate)
                    if candidate:
                        original_event_id_to_supersede = candidate.id

        existing_article_by_hash = self.db.query(Article).filter(Article.hash == content_hash).first()
        if existing_article_by_hash:
            logger.debug(f"SKIP [syndicated duplicate, content already ingested]: {url}")
            self.last_outcome = "duplicate"
            return None  # We already have this exact text from somewhere else
            
        # 4. Fast Extraction & Cluster - Near duplicate (Title Jaccard)
        # We use a high threshold (0.85) to catch obvious duplicates without wasting LLM tokens.
        from datetime import datetime, timedelta, timezone
        forty_eight_hours_ago = datetime.now(timezone.utc) - timedelta(hours=48)
        
        recent_articles = self.db.query(Article).filter(Article.ingested_at >= forty_eight_hours_ago).order_by(Article.ingested_at.desc()).limit(200).all()
        matched_event = None
        
        if not is_same_url_update:
            for ra in recent_articles:
                same_outlet = (
                    ra.source_id == source_id
                    and titles_are_same_outlet_paraphrase(title, ra.title)
                )
                same_release = titles_are_same_release_wording(title, ra.title)
                if not (
                    titles_are_safe_lexical_match(title, ra.title, threshold=0.85)
                    or same_outlet
                    or same_release
                ):
                    continue
                from app.models.event import EventArticle
                link = self.db.query(EventArticle).filter(EventArticle.article_id == ra.id).first()
                if not link:
                    continue
                matched_event = self.db.query(Event).filter(Event.id == link.event_id).first()
                matched_event = self._live_event(matched_event)
                if matched_event:
                    logger.info(
                        f"MERGE [jaccard+markers] '{title}' → event '{matched_event.headline}' "
                        f"(id={matched_event.id})"
                    )
                    break

        # 5. Classify First (To get entities if not matched yet)
        classification = None
        summary = None
        verified_citations = []
        if not matched_event:
            self._release_db()
            try:
                classification = self.llm.classify_event(content)
            except LlmUnavailableError:
                self.last_outcome = "llm_unavailable"
                logger.error("LLM unavailable; refusing to create a mock event for %s", url)
                raise
            except Exception as exc:
                # Defense in depth: the LLMProvider contract requires
                # every implementation to raise LlmUnavailableError for
                # any unavailability (see _unavailable_on_any_error in
                # providers/llm.py for the built-in providers), but this
                # pipeline must not silently trust every current and
                # future provider to honor that perfectly. Anything else
                # escaping here is treated the same way an outage is —
                # never silently counted as an ordinary rejected article,
                # which would make a real outage indistinguishable from a
                # quiet news day. See docs/RED_TEAM_REPORT.md SCHED-OUTAGE-01.
                self.last_outcome = "llm_unavailable"
                logger.error("LLM raised an unexpected error for %s (treated as unavailable): %s", url, exc)
                raise LlmUnavailableError(f"classify_event failed: {type(exc).__name__}: {exc}") from exc
            score = normalize_importance_score(
                classification.importance_score if classification else None
            )

            # Security / Low-value filter (0, missing, or non-numeric → drop)
            if not classification or score is None:
                logger.info(f"REJECT [importance missing/zero or prompt injection]: {url}")
                self.db.rollback()
                return None

            kind = getattr(classification, "event_kind", None) or "other"
            scope = getattr(classification, "technical_change_scope", None) or "product"
            security = getattr(classification, "security_impact", None) or "none"
            inf_kind, inf_scope, inf_sec = infer_event_signals(title, None, content)
            if kind == "other":
                kind = inf_kind
            if kind == inf_kind:
                rank = {"narrow": 0, "product": 1, "platform": 2, "ecosystem": 3}
                if rank.get(inf_scope, 0) > rank.get(str(scope).lower(), 0):
                    scope = inf_scope
            if security == "none" and inf_sec != "none":
                security = inf_sec
            score = calibrate_importance_score(score, kind, scope, security)
            if score is None:
                logger.info(f"REJECT [importance missing/zero or prompt injection]: {url}")
                self.db.rollback()
                return None
            classification.importance_score = score
            classification.event_kind = kind
            classification.technical_change_scope = scope
            classification.security_impact = security

            logger.info(
                f"CLASSIFY [{url}] score={classification.importance_score} "
                f"entities={classification.entities}"
            )

            # 6. Semantic Clustering (Using extracted entities and LLM validation)
            checked_candidate_ids = set()

            def find_semantic_match():
                if is_same_url_update or not classification.entities:
                    return None
                recent_events = self.db.query(Event).filter(Event.created_at >= forty_eight_hours_ago).order_by(Event.created_at.desc()).limit(50).all()
                for candidate in recent_events:
                    if candidate.superseded_by_id or candidate.id in checked_candidate_ids:
                        continue
                    checked_candidate_ids.add(candidate.id)
                    
                    summary_lower = candidate.short_summary.lower() if candidate.short_summary else ""
                    headline_lower = candidate.headline.lower() if candidate.headline else ""
                    stored_entities = [e.lower() for e in (candidate.entities or [])]

                    overlap = False
                    for entity in classification.entities:
                        entity_lower = entity.lower()
                        if (entity_lower in summary_lower
                                or entity_lower in headline_lower
                                or entity_lower in stored_entities):
                            overlap = True
                            break

                    if overlap:
                        candidate_kind = None
                        candidate_reasoning = candidate.importance_reasoning
                        if isinstance(candidate_reasoning, dict):
                            candidate_kind = candidate_reasoning.get("event_kind")
                        if not kinds_are_compatible(kind, candidate_kind):
                            logger.info(
                                "SKIP [kind incompatible] incoming=%s candidate=%s '%s' vs '%s'",
                                kind, candidate_kind, title[:60], candidate.headline[:60],
                            )
                            continue

                        context_hint = None
                        if kind and kind != "other":
                            context_hint = f"Event kind context — existing event: {candidate_kind or 'unknown'}; incoming article: {kind}."

                        existing = "\n".join(
                            part for part in (candidate.headline or "", candidate.short_summary or "") if part
                        )
                        self._release_db()
                        try:
                            rel_result = self.llm.classify_relationship(content, existing, context=context_hint)
                        except LlmUnavailableError:
                            self.last_outcome = "llm_unavailable"
                            raise
                        except Exception as exc:
                            # Same defense-in-depth as classify_event — see
                            # docs/RED_TEAM_REPORT.md SCHED-OUTAGE-01.
                            # Also load-bearing for merge correctness: an
                            # outage silently treated as RelationshipResult
                            # DIFFERENT_EVENT (rather than aborting) would
                            # flood the feed with duplicate canonical events
                            # instead of blocking ingestion, which is worse.
                            self.last_outcome = "llm_unavailable"
                            logger.error(
                                "LLM raised an unexpected error during relationship classification "
                                "for %s (treated as unavailable): %s", url, exc,
                            )
                            raise LlmUnavailableError(
                                f"classify_relationship failed: {type(exc).__name__}: {exc}"
                            ) from exc
                        logger.info(
                            "LLM RELATIONSHIP '%s' vs '%s': %s — %s",
                            title[:60], (candidate.headline or "")[:60],
                            rel_result.relationship, rel_result.reasoning[:80],
                        )
                        if rel_result.is_merge():
                            live_ev = self._live_event(candidate)
                            logger.info(
                                f"MERGE [entity+LLM match] '{title}' → event '{live_ev.headline}' "
                                f"(id={live_ev.id})"
                            )
                            return live_ev
                return None

            if classification is not None and not classification.entities:
                named = list(getattr(classification, "primary_entities", None) or [])
                named.extend(title_versioned_entities(title))
                deduped = []
                for item in named:
                    if isinstance(item, str) and item and item not in deduped:
                        deduped.append(item)
                if deduped:
                    classification.entities = deduped

            if not matched_event:
                matched_event = find_semantic_match()

            if not matched_event:
                self._release_db()
                try:
                    summary = self.llm.summarize_event(content)
                except LlmUnavailableError:
                    self.last_outcome = "llm_unavailable"
                    logger.error("LLM unavailable; refusing to create a mock event for %s", url)
                    raise
                except Exception as exc:
                    # Same defense-in-depth as classify_event above — see
                    # docs/RED_TEAM_REPORT.md SCHED-OUTAGE-01.
                    self.last_outcome = "llm_unavailable"
                    logger.error("LLM raised an unexpected error for %s (treated as unavailable): %s", url, exc)
                    raise LlmUnavailableError(f"summarize_event failed: {type(exc).__name__}: {exc}") from exc
                    
                raw_citations = summary.citations if summary else []
                verified_citations = verify_citations(content, raw_citations)
                if not verified_citations and summary is not None:
                    verified_citations = fallback_source_citations(
                        content,
                        short_summary=summary.short_summary,
                        what_changed=summary.what_changed,
                    )
                logger.info(
                    "SUMMARIZE [%s] citations_raw=%s citations_verified=%s json_mode=%s",
                    url,
                    len(raw_citations or []),
                    len(verified_citations),
                    getattr(self.llm, "_json_mode", None),
                )

        # We wrap the final persist in a retry loop because SQLite under high
        # concurrent ingestion may raise locks or flush errors.
        max_retries = 3
        import sqlalchemy.exc
        
        for attempt in range(max_retries):
            try:
                # Persist new article (Evidence) inside the retry loop
                excerpt = content[:497] + "..." if len(content) > 500 else content
                new_article = Article(
                    source_id=source_id,
                    url=url,
                    title=title,
                    raw_content=content,
                    body_excerpt=excerpt,
                    published_at=article_data.published_at,
                    hash=generate_content_hash(content),
                    image_url=sanitize_http_url(image_url, keep_query=True) or None,
                    publisher_name=publisher_name,
                )
                try:
                    self.db.add(new_article)
                    self.db.flush() # flush to get ID and ACQUIRE SQLite WRITE LOCK
                except IntegrityError:
                    self.db.rollback()
                    self.last_outcome = "duplicate"
                    return None # Race condition caught, article already ingested by another worker
                
                # Now that we hold the write lock, do one FINAL semantic check.
                # While we were waiting for the lock, another worker might have inserted the Event.
                if not matched_event and summary is not None and classification is not None:
                    late_match = find_semantic_match()
                    if late_match:
                        matched_event = late_match
                
                if matched_event:
                    # Associate as additional coverage for the existing canonical event
                    from app.models.event import EventArticle
                    link = EventArticle(
                        event_id=matched_event.id,
                        article_id=new_article.id,
                        link_type="supporting"
                    )
                    self.db.add(link)
                    self.db.commit()
                    self.last_outcome = "linked"
                    logger.info(f"LINKED [supporting evidence] article={new_article.id} → event={matched_event.id}")
                    return matched_event
                
                # 7. Store new canonical event (summary already produced before the write lock)
                if summary is None:
                    self.db.rollback()
                    self.last_outcome = "rejected"
                    logger.error("NEW EVENT aborted: summary missing before persist for %s", url)
                    return None
                
                version = 1
                original_event = None
                if original_event_id_to_supersede:
                    original_event = self.db.query(Event).filter(Event.id == original_event_id_to_supersede).first()
                    if original_event:
                        version = original_event.version + 1
                
                # The canonical display URL must always be the original clean URL — never the
                # dedup-modified version (e.g. "#update-abc12345") which would break "Official Source".
                canonical_display_url = url.split("#update-")[0] if "#update-" in url else url
                
                short_summary = (summary.short_summary or "").strip() if summary else ""
                if not short_summary and summary is not None:
                    short_summary = first_factual_line(summary.what_changed)
                if not short_summary:
                    short_summary = first_source_excerpt(content)
                primary_entities, mentioned_entities = select_primary_entities(
                    primary=getattr(classification, "primary_entities", None) if classification else None,
                    mentioned=getattr(classification, "mentioned_entities", None) if classification else None,
                    all_entities=classification.entities if classification else None,
                    headline=summary.headline if summary else title,
                    summary=short_summary,
                )
                from app.models.source import Source as SourceModel
                ingest = self.db.query(SourceModel).filter(SourceModel.id == source_id).first()
                origin = resolve_originating_source(
                    ingest_name=ingest.name if ingest else None,
                    ingest_url=ingest.url if ingest else None,
                    article_url=canonical_display_url,
                    publisher_name=publisher_name or getattr(new_article, "publisher_name", None),
                )
                reasoning = None
                if classification:
                    reasoning = {
                        "text": classification.importance_reasoning,
                        "event_kind": getattr(classification, "event_kind", None),
                        "scope": getattr(classification, "technical_change_scope", None),
                        "security_impact": getattr(classification, "security_impact", None),
                    }
                new_event = Event(
                    headline=summary.headline if summary else title,
                    short_summary=short_summary,
                    what_changed=summary.what_changed if summary else None,
                    citations=verified_citations,
                    entities=primary_entities,
                    mentioned_entities=mentioned_entities,
                    primary_source_id=source_id,
                    importance_score=classification.importance_score if classification else 50,
                    importance_reasoning=reasoning,
                    image_url=new_article.image_url,
                    article_url=canonical_display_url,
                    official_source_name=origin.official_name if origin.used_official else None,
                    event_time=new_article.published_at,
                    version=version
                )
                self.db.add(new_event)
                self.db.flush()
                
                if original_event:
                    original_event.superseded_by_id = new_event.id
                    self.db.add(original_event)
                    
                # Link Primary Article
                from app.models.event import EventArticle
                primary_link = EventArticle(
                    event_id=new_event.id,
                    article_id=new_article.id,
                    link_type="primary"
                )
                self.db.add(primary_link)
                self.db.commit()
                self.last_outcome = "created"
                logger.info(
                    f"NEW EVENT created: id={new_event.id} headline='{new_event.headline}' "
                    f"score={new_event.importance_score} version={new_event.version}"
                )
                return new_event
            except (sqlalchemy.exc.OperationalError, sqlalchemy.exc.InvalidRequestError, sqlalchemy.exc.DatabaseError) as e:
                self.db.rollback()
                if attempt == max_retries - 1:
                    logger.error("Concurrency retry limit reached: %s", e)
                    raise
                # Concurrency lock or flush failure. Retry by checking if a matched_event was created.
                if summary is not None and classification is not None:
                    late_match = find_semantic_match()
                    if late_match:
                        matched_event = late_match

    def _live_event(self, event: Optional[Event]) -> Optional[Event]:
        """Follow superseded_by_id so supporting articles attach to the visible event."""
        seen = set()
        current = event
        while current and current.superseded_by_id and current.id not in seen:
            seen.add(current.id)
            nxt = self.db.query(Event).filter(Event.id == current.superseded_by_id).first()
            if not nxt:
                break
            current = nxt
        return current
