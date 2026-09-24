from typing import Optional, Callable
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import logging

from app.models.article import Article
from app.models.event import Event
from app.core.providers.llm import (
    EventRelationship,
    get_llm_provider,
    LlmUnavailableError,
    resolve_llm_mode,
)
from app.core.runtime import is_test_runtime
from app.core.deduplication import (
    normalize_url,
    generate_content_hash,
    is_immaterial_change,
    claim_stems,
    validate_evidence,
    fallback_source_citations,
    classify_headline_relationship,
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
from app.core.headlines import restore_headline_organization
from app.core.origin import resolve_originating_source
from app.core.article_body import enrich_article, MIN_CONTENT_CHARS

logger = logging.getLogger(__name__)

ENRICHMENT_PENDING = "pending"
# LLM relationship checks per incoming article, over the most similar candidates.
MAX_RELATIONSHIP_CHECKS = 5
# How long a known article is still re-fetched to look for material edits.
from datetime import timedelta as _timedelta
UPDATE_RECHECK_WINDOW = _timedelta(days=7)


class IntelligencePipeline:
    def __init__(self, db: Session, llm_env: Optional[str] = None):
        self.db = db
        self.llm_mode = resolve_llm_mode(llm_env)
        self.llm = get_llm_provider(env=llm_env)
        logger.info("pipeline llm=%s mode=%s", type(self.llm).__name__, self.llm_mode)
        self.last_outcome: Optional[str] = None
        # False during a provider outage: articles are fetched, deduplicated
        # and stored as pending, but the LLM is not called and no event is
        # created. Nothing semantic is produced without the LLM.
        self.enrichment_enabled = True
        self._pending_ctx: Optional[dict] = None

    def process_article(
        self,
        article_data: 'ArticleData',
        source_id: str,
        fetch_fn: Optional[Callable] = None,
        pending_article_id=None,
    ) -> Optional[Event]:
        """
        Runs the full ingestion pipeline for a single article.
        Returns the canonical Event this article was clustered into.
        last_outcome is one of: created, linked, duplicate, rejected,
        pending (stored, enrichment deferred), llm_unavailable.

        When the LLM is unavailable the article is stored as pending before
        LlmUnavailableError propagates, so an outage never loses it.
        pending_article_id retries a stored pending article in place.
        """
        self._pending_ctx = None
        try:
            result = self._process_article(article_data, source_id, fetch_fn, pending_article_id)
        except LlmUnavailableError as exc:
            self.last_outcome = "llm_unavailable"
            self.db.rollback()
            self._store_pending(str(exc))
            raise
        if pending_article_id is not None and self.last_outcome in ("rejected", "duplicate"):
            self._close_pending(pending_article_id, self.last_outcome)
        return result

    def _store_pending(self, reason: str) -> None:
        """Persist the fetched article so enrichment can be retried. Never creates an event."""
        ctx = self._pending_ctx
        if not ctx:
            return
        from app.core.logger import redact_secrets

        # Provider exception text can echo request details; never store credentials.
        reason = redact_secrets(reason or "enrichment unavailable")[:300]
        try:
            existing = self.db.query(Article).filter(Article.url == ctx["url"]).first()
            if existing is not None:
                if existing.enrichment_status == ENRICHMENT_PENDING:
                    existing.enrichment_error = reason
                    self.db.commit()
                return
            self.db.add(Article(
                source_id=ctx["source_id"],
                url=ctx["url"],
                title=ctx["title"],
                raw_content=ctx["content"],
                body_excerpt=ctx["content"][:497] + "..." if len(ctx["content"]) > 500 else ctx["content"],
                published_at=ctx["published_at"],
                hash=ctx["hash"],
                image_url=sanitize_http_url(ctx["image_url"], keep_query=True) or None,
                publisher_name=ctx["publisher_name"],
                enrichment_status=ENRICHMENT_PENDING,
                enrichment_error=reason,
            ))
            self.db.commit()
            logger.info("PENDING [enrichment deferred] %s (%s)", ctx["url"], reason[:80])
        except IntegrityError:
            self.db.rollback()
        except Exception as exc:
            self.db.rollback()
            logger.error("Could not store pending article %s: %s", ctx.get("url"), exc)

    def _close_pending(self, article_id, outcome: str) -> None:
        """A retried pending article that enrichment rejected is not retried again."""
        try:
            row = self.db.query(Article).filter(Article.id == article_id).first()
            if row is not None and row.enrichment_status == ENRICHMENT_PENDING:
                row.enrichment_status = outcome
                row.enrichment_error = None
                self.db.commit()
        except Exception:
            self.db.rollback()

    def _settled_known_url(self, url: str) -> bool:
        """
        A processed article older than UPDATE_RECHECK_WINDOW is not fetched
        again to look for edits. Feeds list the same 100 posts on every poll;
        re-downloading months-old pages each cycle was hundreds of fetches.
        """
        from datetime import datetime, timezone

        known = (
            self.db.query(Article.published_at, Article.ingested_at, Article.enrichment_status)
            .filter(Article.url == url)
            .first()
        )
        if known is None or known.enrichment_status == ENRICHMENT_PENDING:
            return False
        # Watched for edits for a window after we first stored it, however old
        # its publication date: a newly discovered old post is still checked.
        reference = known.ingested_at or known.published_at
        if reference is None:
            return False
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - reference > UPDATE_RECHECK_WINDOW

    def _release_db(self) -> None:
        """End the current transaction so SQLite is not held across NVIDIA/LLM calls."""
        try:
            if self.db.in_transaction():
                self.db.commit()
        except Exception:
            self.db.rollback()

    def _process_article(
        self,
        article_data: 'ArticleData',
        source_id: str,
        fetch_fn: Optional[Callable] = None,
        pending_article_id=None,
    ) -> Optional[Event]:
        from app.models.event import EventArticle

        self.last_outcome = "rejected"

        if article_data is None:
            return None

        pending_article = None
        if pending_article_id is not None:
            pending_article = self.db.query(Article).filter(Article.id == pending_article_id).first()
            if pending_article is None or pending_article.enrichment_status != ENRICHMENT_PENDING:
                self.last_outcome = "duplicate"
                return None

        # 1. Normalize
        url = pending_article.url if pending_article is not None else normalize_url(article_data.url)
        title = article_data.title
        content = article_data.content or ""

        if not url or not title:
            logger.debug(f"REJECT [missing url or title]: url={article_data.url!r}")
            return None

        if is_obvious_noise(title, content):
            logger.info(f"REJECT [deterministic noise]: {url}")
            return None

        if pending_article is None and self._settled_known_url(url):
            # Known and older than the update window: not re-downloaded.
            self.last_outcome = "duplicate"
            return None

        if fetch_fn is None and not is_test_runtime():
            from app.core.fetcher import fetch_url
            fetch_fn = fetch_url

        from app.core.origin import is_aggregator_source
        from app.models.source import Source as IngestSource
        ingest_row = self.db.query(IngestSource).filter(IngestSource.id == source_id).first()
        fetch_publisher = bool(
            ingest_row and is_aggregator_source(ingest_row.name, ingest_row.url)
        )
        if pending_article is not None:
            # Already fetched and enriched when it was stored; never refetch.
            content = pending_article.raw_content or ""
            image_url = pending_article.image_url
            publisher_name = pending_article.publisher_name
        else:
            content, image_url, publisher_name = enrich_article(
                title,
                url,
                content,
                article_data.image_url,
                fetch_fn=fetch_fn,
                fetch_publisher=fetch_publisher,
            )

        # 2. Validate minimum content length
        stripped_content = content.strip()
        if len(stripped_content) < MIN_CONTENT_CHARS:
            logger.debug(f"REJECT [content too short ({len(stripped_content)} chars)]: {url}")
            return None
        content = stripped_content
            
        # 3. Deduplicate - Exact URL or Exact Content Hash
        content_hash = generate_content_hash(content)
        if pending_article is not None:
            existing_article_by_url = None
        else:
            existing_article_by_url = self.db.query(Article).filter(Article.url == url).first()

        is_same_url_update = False
        original_event_id_to_supersede = None

        if existing_article_by_url is not None and existing_article_by_url.enrichment_status == ENRICHMENT_PENDING:
            # Seen again in the feed while waiting for enrichment. The stored
            # row is retried by the scheduler; a second row is never created.
            logger.debug(f"SKIP [already stored, enrichment pending]: {url}")
            self.last_outcome = "pending"
            return None

        if pending_article is not None and "#update-" in url:
            # A stored same-URL update: supersede the live version of the original.
            is_same_url_update = True
            base = self.db.query(Article).filter(Article.url == url.split("#update-")[0]).first()
            base_link = (
                self.db.query(EventArticle).filter(EventArticle.article_id == base.id).first()
                if base is not None else None
            )
            if base_link:
                candidate = self._live_event(
                    self.db.query(Event).filter(Event.id == base_link.event_id).first()
                )
                if candidate:
                    original_event_id_to_supersede = candidate.id

        if existing_article_by_url:
            if existing_article_by_url.hash == content_hash:
                logger.debug(f"SKIP [exact duplicate, hash unchanged]: {url}")
                self.last_outcome = "duplicate"
                return None  # Exact duplicate, nothing changed
            # Compared with every stored version of this URL (bounded):
            # ingested_at has one-second resolution, so "latest" is not
            # reliably orderable, and text matching any known version
            # carries no new information.
            known_versions = (
                self.db.query(Article.hash, Article.raw_content)
                .filter((Article.url == url) | Article.url.like(f"{url}#update-%"))
                .order_by(Article.ingested_at.desc())
                .limit(10)
                .all()
            )
            if any(
                known_hash == content_hash or is_immaterial_change(known_content, content)
                for known_hash, known_content in known_versions
            ):
                # Page chrome such as vote counts and "3 days ago" changes on
                # every fetch. Re-summarizing it would create a new version,
                # spend two LLM calls, and look like a new development.
                logger.debug(f"SKIP [immaterial change at same URL]: {url}")
                self.last_outcome = "duplicate"
                return None
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

        hash_query = self.db.query(Article).filter(Article.hash == content_hash)
        if pending_article is not None:
            hash_query = hash_query.filter(Article.id != pending_article.id)
        existing_article_by_hash = hash_query.first()
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

        # Everything the article needs to be stored durably if enrichment
        # cannot run now. Deterministic work above (dedup, fast merge) is done.
        self._pending_ctx = {
            "url": url,
            "title": title,
            "content": content,
            "hash": content_hash,
            "published_at": article_data.published_at,
            "image_url": image_url,
            "publisher_name": publisher_name,
            "source_id": source_id,
        }

        # 5. Classify First (To get entities if not matched yet)
        classification = None
        summary = None
        verified_citations = []
        if not matched_event and not self.enrichment_enabled:
            self._release_db()
            if pending_article is None:
                self._store_pending("LLM unavailable; enrichment deferred")
            self.last_outcome = "pending"
            return None
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
            relationship_calls = {"count": 0}
            incoming_stems = claim_stems(f"{title} {content[:600]}")
            incoming_entities = {entity.lower() for entity in classification.entities or []}

            def candidate_affinity(candidate) -> tuple:
                """How much a candidate shares beyond one common entity (deterministic)."""
                text = f"{candidate.headline or ''} {candidate.short_summary or ''}"
                shared_words = len(incoming_stems & claim_stems(text))
                shared_entities = len(incoming_entities & {e.lower() for e in (candidate.entities or []) if isinstance(e, str)})
                return (shared_words + shared_entities, shared_words)

            def find_semantic_match():
                if is_same_url_update or not classification.entities:
                    return None
                recent_events = self.db.query(Event).filter(Event.created_at >= forty_eight_hours_ago).order_by(Event.created_at.desc()).limit(50).all()
                # Most similar first, then at most MAX_RELATIONSHIP_CHECKS LLM
                # calls per article. Sharing only "OpenAI" used to send an
                # article to the LLM against up to 22 events, one ~30s call each.
                recent_events.sort(key=candidate_affinity, reverse=True)
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
                        if relationship_calls["count"] >= MAX_RELATIONSHIP_CHECKS:
                            logger.info("RELATIONSHIP [check budget reached] %s", url)
                            return None
                        relationship_calls["count"] += 1
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
                claim = " ".join(
                    part for part in (
                        getattr(summary, "headline", None) if summary else None,
                        summary.short_summary if summary else None,
                        summary.what_changed if summary else None,
                    ) if part
                )
                verified_citations = validate_evidence(content, raw_citations, claim=claim)
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
                if summary is not None and summary.headline:
                    # A generated "Startup raises ..." regains the name the
                    # publisher's own title uses, when that name is certain.
                    publishers = [publisher_name]
                    if ingest_row is not None:
                        publishers.append(ingest_row.name)
                        if ingest_row.organization is not None:
                            publishers.append(ingest_row.organization.name)
                    restored = restore_headline_organization(
                        summary.headline,
                        source_title=title,
                        content=content,
                        entities=(
                            list(getattr(classification, "primary_entities", None) or [])
                            + list(classification.entities or [])
                        ),
                        publisher_names=[name for name in publishers if name],
                    )
                    if restored != summary.headline:
                        logger.info("HEADLINE [organization restored] %r -> %r", summary.headline, restored)
                        summary.headline = restored

        if not matched_event and summary is not None and getattr(summary, "headline", None):
            from datetime import datetime, timedelta, timezone
            window_start = datetime.now(timezone.utc) - timedelta(days=7)
            incoming_kind = getattr(classification, "event_kind", None) or ""
            recent_events = (
                self.db.query(Event)
                .filter(Event.superseded_by_id.is_(None), Event.created_at >= window_start)
                .order_by(Event.created_at.desc())
                .limit(80)
                .all()
            )
            incoming_headline = summary.headline or title
            for candidate in recent_events:
                candidate_kind = ""
                if isinstance(candidate.importance_reasoning, dict):
                    candidate_kind = candidate.importance_reasoning.get("event_kind") or ""
                relationship = classify_headline_relationship(
                    incoming_headline,
                    candidate.headline or "",
                    incoming_kind,
                    candidate_kind,
                )
                if relationship != EventRelationship.SAME_EVENT:
                    continue
                matched_event = self._live_event(candidate)
                if matched_event:
                    logger.info(
                        "MERGE [same development] '%s' → event '%s' (id=%s)",
                        incoming_headline[:80],
                        matched_event.headline,
                        matched_event.id,
                    )
                    break

        # We wrap the final persist in a retry loop because SQLite under high
        # concurrent ingestion may raise locks or flush errors.
        max_retries = 3
        import sqlalchemy.exc
        
        for attempt in range(max_retries):
            try:
                # Persist new article (Evidence) inside the retry loop
                excerpt = content[:497] + "..." if len(content) > 500 else content
                if pending_article is not None:
                    # Promote the stored row; it is the same article, not a new one.
                    new_article = self.db.query(Article).filter(Article.id == pending_article.id).first()
                    if new_article is None or new_article.enrichment_status != ENRICHMENT_PENDING:
                        self.db.rollback()
                        self.last_outcome = "duplicate"
                        return None
                    new_article.enrichment_status = None
                    new_article.enrichment_error = None
                    self.db.flush()
                else:
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
