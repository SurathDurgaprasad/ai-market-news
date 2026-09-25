"""
Source-aware ingestion scheduling.

polling_tier drives freshness, not a single global interval:

    high   → 10 minutes  (official blogs, fast-moving journalism)
    medium → 20 minutes  (product target freshness)
    low    → 60 minutes  (infrequent publishers)

A 5-minute ticker evaluates which enabled sources are due. Failed sources
get exponential backoff so a persistently broken feed is not hammered.

Source type is compared case-insensitively ("rss" and "RSS" are equivalent).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.db.session import SessionLocal
from app.models.source import Source

logger = logging.getLogger(__name__)

POLLING_INTERVAL_MINUTES = {
    "high": 10,
    "medium": 20,
    "low": 60,
}
TICK_MINUTES = 5
MAX_BACKOFF_MINUTES = 240  # 4 hours
# After a provider outage is observed, the provider is not called again
# until this has passed. Sources are still fetched and new articles stored
# as pending, so one dead provider costs one deadline, not one per article.
PROVIDER_OUTAGE_COOLDOWN = timedelta(minutes=15)
# Pending articles retried per cycle once the provider is reachable.
PENDING_RETRY_LIMIT = 20


def polling_interval_minutes(source: Source) -> int:
    """Effective polling interval including failure backoff."""
    tier = (source.polling_tier or "medium").lower()
    base = POLLING_INTERVAL_MINUTES.get(tier, 20)
    failures = source.consecutive_failures or 0
    if (source.health_status or "").lower() == "failing" and failures > 0:
        backed = base * (2 ** min(int(failures), 4))
        return min(backed, MAX_BACKOFF_MINUTES)
    return base


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_source_due(source: Source, now: Optional[datetime] = None) -> bool:
    """True if this source should be fetched on this tick."""
    now = _as_utc(now) or datetime.now(timezone.utc)
    interval = timedelta(minutes=polling_interval_minutes(source))

    last = _as_utc(source.last_fetch_at)
    if (source.health_status or "").lower() == "failing":
        failure = _as_utc(source.last_failure_at)
        candidates = [t for t in (last, failure) if t is not None]
        last = max(candidates) if candidates else None

    if last is None:
        return True
    return now >= last + interval


def is_rss_source(source_type: Optional[str]) -> bool:
    return (source_type or "").lower() == "rss"


class IngestionScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.provider_outage_until: Optional[datetime] = None

    def enrichment_paused(self, now: Optional[datetime] = None) -> bool:
        return not self._enrichment_allowed(_as_utc(now) or datetime.now(timezone.utc))

    def _enrichment_allowed(self, now: datetime) -> bool:
        return self.provider_outage_until is None or now >= self.provider_outage_until

    def _mark_provider_outage(self, now: datetime, reason) -> None:
        self.provider_outage_until = now + PROVIDER_OUTAGE_COOLDOWN
        logger.error(
            "LLM provider unavailable (%s); enrichment paused until %s. "
            "Sources keep being fetched; new articles are stored as pending.",
            str(reason)[:200],
            self.provider_outage_until.isoformat(),
        )

    def retry_pending_enrichment(self, now: datetime) -> bool:
        """
        Enrich stored pending articles, oldest first, bounded per cycle.
        Returns False if the provider failed again (outage continues).
        """
        from app.core.parser import ArticleData
        from app.core.pipeline import ENRICHMENT_PENDING, IntelligencePipeline
        from app.core.providers.llm import LlmUnavailableError
        from app.models.article import Article

        db = SessionLocal()
        try:
            rows = (
                db.query(Article.id, Article.source_id)
                .filter(Article.enrichment_status == ENRICHMENT_PENDING)
                .order_by(Article.ingested_at.asc())
                .limit(PENDING_RETRY_LIMIT)
                .all()
            )
            if not rows:
                return True
            pipeline = IntelligencePipeline(db)
            outcomes: dict = {}
            for article_id, source_id in rows:
                row = db.query(Article).filter(Article.id == article_id).first()
                if row is None:
                    continue
                data = ArticleData(
                    title=row.title,
                    url=row.url,
                    content=row.raw_content or "",
                    published_at=row.published_at,
                    image_url=row.image_url,
                )
                try:
                    pipeline.process_article(data, source_id, pending_article_id=article_id)
                except LlmUnavailableError as exc:
                    db.rollback()
                    self._mark_provider_outage(now, exc)
                    logger.info("pending retry stopped by outage: %s", outcomes)
                    return False
                except Exception as exc:
                    db.rollback()
                    logger.error("pending retry failed for article=%s: %s", article_id, exc)
                    continue
                outcome = pipeline.last_outcome or "rejected"
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
            logger.info("pending retry outcomes: %s", outcomes)
            return True
        finally:
            db.close()

    def start(self):
        self.scheduler.add_job(
            func=self.run_ingestion_cycle,
            trigger=IntervalTrigger(minutes=TICK_MINUTES),
            id="ingestion_cycle",
            name="Evaluate due sources and ingest",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(
            "Ingestion scheduler started (tick=%sm, high=%sm, medium=%sm, low=%sm).",
            TICK_MINUTES,
            POLLING_INTERVAL_MINUTES["high"],
            POLLING_INTERVAL_MINUTES["medium"],
            POLLING_INTERVAL_MINUTES["low"],
        )

    def stop(self):
        self.scheduler.shutdown()
        logger.info("Ingestion scheduler stopped.")

    def run_ingestion_cycle(self, now: Optional[datetime] = None):
        logger.info("Starting ingestion cycle...")
        now = _as_utc(now) or datetime.now(timezone.utc)

        try:
            from app.core.fetcher import fetch_url
            from app.core.parser import parse_rss_feed, extract_feed_next_url, looks_like_feed
            from app.core.pipeline import IntelligencePipeline
            from app.core.providers.llm import (
                resolve_llm_mode,
                LlmUnavailableError,
                LLM_UNAVAILABLE,
                configured_llm_provider_name,
            )
            from sqlalchemy.sql import func

            llm_mode = resolve_llm_mode()
            llm_provider = configured_llm_provider_name()
            logger.info("ingestion_cycle llm_mode=%s llm_provider=%s", llm_mode, llm_provider)
            if llm_mode == LLM_UNAVAILABLE:
                logger.error(
                    "INGESTION BLOCKED: production path has no usable LLM "
                    "(LLM_PROVIDER=%s). No TestLLM mock events will be created.",
                    llm_provider,
                )
                return {"blocked": "llm_unavailable", "llm_mode": llm_mode, "llm_provider": llm_provider}

            db_master = SessionLocal()
            try:
                sources = db_master.query(Source).filter(Source.enabled == True).all()  # noqa: E712
                source_targets = [
                    (s.id, s.name, s.url, s.type)
                    for s in sources
                    if is_source_due(s, now)
                ]
                skipped = len(sources) - len(source_targets)
                logger.info(
                    "Due sources: %s of %s enabled (%s not yet due).",
                    len(source_targets),
                    len(sources),
                    skipped,
                )
            finally:
                db_master.close()

            # Fetch/parse and LLM enrichment are separate. When the provider
            # is down, sources are still fetched and new articles stored as
            # pending (no LLM call, no event); they are enriched on recovery.
            enrichment = self._enrichment_allowed(now)
            if enrichment:
                enrichment = self.retry_pending_enrichment(now)
            else:
                logger.warning(
                    "Enrichment paused until %s; fetching sources in store-only mode",
                    self.provider_outage_until.isoformat() if self.provider_outage_until else "?",
                )
            for source_id, s_name, s_url, s_type in source_targets:
                db = SessionLocal()
                try:
                    source = db.query(Source).filter(Source.id == source_id).first()
                    if not source:
                        continue

                    if not is_rss_source(s_type):
                        logger.info(f"Skipping {s_name}, unsupported type {s_type}")
                        continue

                    logger.info(f"Processing source: {s_name} ({s_url})")

                    try:
                        response = fetch_url(s_url)
                        articles = parse_rss_feed(response.text)
                        if not articles and not looks_like_feed(response.text):
                            # feedparser's own `bozo` flag does not catch this:
                            # an HTML error/notice page (e.g. after a feed URL
                            # 404s or a CMS migration) parses as
                            # bozo=False, entries=0 — indistinguishable from a
                            # genuinely well-formed, currently-empty feed.
                            # Without this check the source would be recorded
                            # health_status="healthy" indefinitely despite no
                            # longer serving a feed at all. See
                            # docs/security-findings.md INGEST-SILENT-01.
                            raise ValueError(
                                "Fetched content does not look like an RSS/Atom/RDF feed "
                                "(no <rss>/<feed>/<rdf:RDF> root element found)"
                            )
                        next_page = extract_feed_next_url(response.text)
                        if next_page:
                            logger.info(
                                "source=%s advertises feed pagination next=%s; "
                                "not following (polling window covers current source set)",
                                s_name,
                                next_page,
                            )
                        logger.info("Parsed %s articles from %s", len(articles), s_name)

                        pipeline = IntelligencePipeline(db)
                        pipeline.enrichment_enabled = enrichment
                        discovered = len(articles)
                        created = linked = rejected = duplicates = llm_errors = pending = 0
                        for article_data in articles:
                            try:
                                pipeline.process_article(article_data, source_id)
                                outcome = pipeline.last_outcome
                                if outcome == "created":
                                    created += 1
                                elif outcome == "linked":
                                    linked += 1
                                elif outcome == "duplicate":
                                    duplicates += 1
                                elif outcome == "pending":
                                    pending += 1
                                else:
                                    rejected += 1
                            except LlmUnavailableError as llm_err:
                                # The pipeline already stored this article as
                                # pending. Stop calling the provider; keep
                                # fetching and storing the rest.
                                logger.error("LLM unavailable while processing %s: %s", s_name, llm_err)
                                llm_errors += 1
                                pending += 1
                                db.rollback()
                                enrichment = False
                                pipeline.enrichment_enabled = False
                                self._mark_provider_outage(now, llm_err)
                            except Exception as art_err:
                                logger.error(f"Failed to process article in {s_name}: {art_err}")
                                rejected += 1
                                db.rollback()

                        summary = (
                            f"discovered={discovered} created={created} linked={linked} "
                            f"rejected={rejected} duplicates={duplicates} pending={pending} "
                            f"llm_errors={llm_errors}"
                        )
                        logger.info(
                            "ingest source=%s %s interval_min=%s",
                            s_name,
                            summary,
                            polling_interval_minutes(source),
                        )

                        source = db.query(Source).filter(Source.id == source_id).first()
                        if source:
                            source.last_ingest_summary = summary[:500]
                            # The fetch itself succeeded either way: not a failure.
                            source.last_fetch_at = func.now()
                            source.consecutive_failures = 0
                            if pending:
                                # Not healthy either: articles are stored but
                                # not yet enriched into events.
                                source.health_status = "degraded"
                                source.last_error_info = (
                                    f"LLM unavailable; {pending} article(s) stored, awaiting enrichment"
                                )
                            else:
                                source.health_status = "healthy"
                                source.last_error_info = None
                            db.commit()

                    except Exception as source_err:
                        logger.error(f"Failed to process source {s_name}: {source_err}")
                        db.rollback()
                        source = db.query(Source).filter(Source.id == source_id).first()
                        if source:
                            source.health_status = "failing"
                            source.last_failure_at = func.now()
                            source.last_error_info = str(source_err)[:500]
                            source.consecutive_failures = (source.consecutive_failures or 0) + 1
                            db.commit()
                except Exception as inner_err:
                    logger.error(f"Critical error handling source {s_name}: {inner_err}")
                finally:
                    db.close()

            db = SessionLocal()
            try:
                from app.core.consolidate import consolidate_safe_duplicates
                merged = consolidate_safe_duplicates(db)
                if merged:
                    logger.info("Consolidated %s duplicate developments into canonical events", merged)
            except Exception as consolidate_err:
                logger.error("Canonical consolidation failed: %s", consolidate_err)
                db.rollback()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error during ingestion cycle: {e}")
        logger.info("Ingestion cycle complete.")

scheduler = IngestionScheduler()
