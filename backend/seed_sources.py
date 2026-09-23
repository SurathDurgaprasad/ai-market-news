"""
Source Registry Initialization Script
======================================
Seeds the database with high-quality AI intelligence sources.

Usage (from the backend/ directory, with venv active):
    python seed_sources.py

This is idempotent: running it multiple times will not create duplicate sources.
Sources are matched by (organization, name) — the stable identity of a curated
entry — falling back to URL for the (rare) case of a genuine rename. Existing
sources are updated in place, including their URL, so correcting a stale feed
URL never orphans the old row as a duplicate.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy.orm import Session
from app.db.session import SessionLocal, engine
from app.db.base_class import Base
from app.models.source import Source, Organization
import uuid
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Source definitions ─────────────────────────────────────────────────────────
# Each entry: (organization_name, source_name, url, tier, polling_tier)
# tier: primary | secondary | community
# polling_tier: high (every ~5min) | medium (every ~15min) | low (every ~60min)

SOURCES = [
    # ── PRIMARY: Official company blogs & research ─────────────────────────────
    ("OpenAI", "OpenAI Blog", "https://openai.com/news/rss.xml", "primary", "high"),
    ("Anthropic", "Anthropic News", "https://www.anthropic.com/news/rss", "primary", "high"),
    ("Google DeepMind", "Google DeepMind Blog", "https://deepmind.google/blog/rss", "primary", "high"),
    # Canonical URL after 308/301 (2026-09-18 live probe)
    ("Google AI", "Google AI Blog", "https://blog.google/innovation-and-ai/technology/ai/rss/", "primary", "high"),
    ("Meta AI", "Meta AI Research", "https://ai.meta.com/blog/rss", "primary", "medium"),
    ("xAI", "xAI Blog", "https://x.ai/blog/rss", "primary", "medium"),
    ("Mistral AI", "Mistral AI News", "https://mistral.ai/news/rss", "primary", "medium"),
    ("DeepSeek", "DeepSeek Blog", "https://deepseek.com/blog/rss", "primary", "medium"),
    ("Cohere", "Cohere Blog", "https://cohere.com/blog/rss", "primary", "low"),
    ("Hugging Face", "Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "primary", "medium"),
    ("Microsoft Research", "Microsoft Research AI Blog", "https://www.microsoft.com/en-us/research/feed/", "primary", "medium"),
    ("NVIDIA", "NVIDIA AI Blog", "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "primary", "medium"),
    ("Stability AI", "Stability AI Blog", "https://stability.ai/blog/rss", "primary", "low"),
    ("Perplexity AI", "Perplexity Blog", "https://www.perplexity.ai/blog/rss", "primary", "low"),
    ("AWS AI", "AWS Machine Learning Blog", "https://aws.amazon.com/blogs/machine-learning/feed/", "primary", "medium"),

    # ── SECONDARY: High-quality AI journalism ─────────────────────────────────
    ("TechCrunch", "TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "secondary", "high"),
    ("The Verge", "The Verge AI", "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "secondary", "high"),
    ("Ars Technica", "Ars Technica AI", "https://feeds.arstechnica.com/arstechnica/technology-lab", "secondary", "medium"),
    ("MIT Technology Review", "MIT Technology Review AI", "https://www.technologyreview.com/topic/artificial-intelligence/feed/", "secondary", "medium"),
    ("VentureBeat", "VentureBeat AI", "https://venturebeat.com/ai/feed/", "secondary", "high"),
    ("Wired", "Wired AI", "https://www.wired.com/feed/tag/ai/rss", "secondary", "medium"),

    # ── COMMUNITY: Developer discussions & discovery ───────────────────────────
    ("Hacker News", "Hacker News", "https://news.ycombinator.com/rss", "community", "high"),
]


def seed(db: Session) -> None:
    inserted = 0
    updated = 0

    # Build organization cache
    org_cache: dict[str, Organization] = {}
    for org_name, *_ in SOURCES:
        if org_name not in org_cache:
            org = db.query(Organization).filter(Organization.name == org_name).first()
            if not org:
                org = Organization(id=uuid.uuid4(), name=org_name)
                db.add(org)
                db.flush()
                logger.info(f"  Created organization: {org_name}")
            org_cache[org_name] = org

    for org_name, source_name, url, tier, polling_tier in SOURCES:
        org = org_cache[org_name]
        # Match by (organization, name) first — the stable identity of a
        # curated source — falling back to URL. Matching by URL alone (the
        # prior behavior) breaks idempotency whenever a source's URL is
        # corrected (e.g. after a redirect/404 is discovered): the old row
        # is orphaned rather than updated, leaving a permanent duplicate
        # "OpenAI Blog"/"Google DeepMind Blog"/etc. entry on the admin
        # sources page. Confirmed live: re-seeding after several URLs were
        # refined produced exactly this duplication.
        existing = (
            db.query(Source)
            .filter(Source.organization_id == org.id, Source.name == source_name)
            .first()
            or db.query(Source).filter(Source.url == url).first()
        )
        if existing:
            # Update metadata if it changed
            existing.name = source_name
            existing.url = url
            existing.tier = tier
            existing.polling_tier = polling_tier
            existing.enabled = True
            updated += 1
        else:
            source = Source(
                id=uuid.uuid4(),
                name=source_name,
                url=url,
                organization_id=org.id,
                type="rss",
                tier=tier,
                polling_tier=polling_tier,
                enabled=True,
                health_status="healthy",
            )
            db.add(source)
            inserted += 1
            logger.info(f"  Added source: {source_name} ({url})")

    db.commit()
    logger.info(f"\nDone. Inserted: {inserted}, Updated: {updated}, Total: {inserted + updated}")


def main() -> None:
    logger.info("Creating tables if they don't exist...")
    Base.metadata.create_all(bind=engine)

    logger.info(f"Seeding AI intelligence sources into database...")
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
