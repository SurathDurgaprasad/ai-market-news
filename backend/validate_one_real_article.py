"""Production validation against openai/gpt-oss-20b. Never prints credentials."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

os.environ["TESTING"] = "0"
os.environ["TEST_MODE"] = "0"
os.environ.setdefault("LLM_PROVIDER", "nvidia")
sys.path.insert(0, os.path.dirname(__file__))

from app.core.providers.llm import (
    NVIDIAProvider,
    TestLLMProvider,
    get_llm_provider,
    resolve_llm_mode,
)
from app.core.config import settings
from app.core.pipeline import IntelligencePipeline
from app.core.parser import parse_rss_feed, ArticleData
from app.core.fetcher import fetch_url
from app.core.deduplication import verify_citations, normalize_url
from app.db.session import SessionLocal
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.models.article import Article


def dump(obj):
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=True))


def main() -> int:
    provider = get_llm_provider()
    report = {
        "llm_mode": resolve_llm_mode(),
        "provider": type(provider).__name__,
        "is_test": isinstance(provider, TestLLMProvider),
        "is_nvidia": isinstance(provider, NVIDIAProvider),
        "model": getattr(provider, "model", None),
        "configured_model": settings.NVIDIA_MODEL,
    }
    if report["is_test"] or not report["is_nvidia"] or report["model"] != "openai/gpt-oss-20b":
        report["status"] = "FAILED"
        dump(report)
        return 2

    article_text = (
        "Mistral AI released Ministral 3, a new family of open-weight models for on-device and edge "
        "deployment. The company said the models are available under Apache 2.0 on Hugging Face and "
        "via the Mistral API. Context length is documented as 128k tokens. This is a software model "
        "release, not a cloud-only API wrapper."
    )
    cls = provider.classify_event(article_text)
    summary = provider.summarize_event(article_text)
    cites = verify_citations(article_text, summary.citations if summary else [])
    report["schema"] = {
        "classify": None if cls is None else cls.model_dump(),
        "summary_headline": None if summary is None else summary.headline,
        "summary_ok": summary is not None,
        "why_it_matters_in_summary": False if summary is None else ("why it matters" in f"{summary.headline} {summary.short_summary} {summary.what_changed}".lower()),
        "verified_citations": len(cites),
        "raw_citations": len(summary.citations or []) if summary else 0,
        "json_mode": provider._json_mode,
        "status": "VERIFIED" if (cls and summary and cls.entities and 1 <= cls.importance_score <= 100) else "FAILED",
    }

    db = SessionLocal()
    existing_urls = {normalize_url(a.url) for a in db.query(Article).all() if a.url}
    feed_url = "https://mistral.ai/news/rss"
    items = parse_rss_feed(fetch_url(feed_url).text)
    chosen = None
    for item in items:
        url = normalize_url(item.url)
        if url and url not in existing_urls:
            chosen = item
            break
    if chosen is None:
        feed_url = "https://huggingface.co/blog/feed.xml"
        items = parse_rss_feed(fetch_url(feed_url).text)
        for item in items:
            url = normalize_url(item.url)
            if url and url not in existing_urls:
                chosen = item
                break

    source = db.query(Source).filter(Source.url == feed_url).first()
    if source is None:
        source = Source(name="Live Validation Source", url=feed_url, type="rss", enabled=True, tier="primary")
        db.add(source)
        db.commit()

    pipeline = IntelligencePipeline(db)
    report["pipeline_llm"] = type(pipeline.llm).__name__
    report["pipeline_is_test"] = isinstance(pipeline.llm, TestLLMProvider)
    if isinstance(pipeline.llm, TestLLMProvider):
        report["status"] = "FAILED"
        dump(report)
        return 2
    pipeline.llm = provider

    if chosen is None:
        report["e2e"] = {"status": "FAILED", "error": "no unseen RSS item"}
        dump(report)
        return 1

    event = pipeline.process_article(chosen, source.id)
    db.expire_all()
    persisted = db.query(Event).filter(Event.id == event.id).first() if event else None
    article_row = db.query(Article).filter(Article.url == normalize_url(chosen.url)).first()
    report["e2e"] = {
        "status": "VERIFIED" if persisted and persisted.headline != "Mock Headline for TestCorp" else "FAILED",
        "rss_title": chosen.title,
        "rss_url": chosen.url,
        "published_at": chosen.published_at,
        "outcome": pipeline.last_outcome,
        "event_id": str(persisted.id) if persisted else None,
        "headline": persisted.headline if persisted else None,
        "entities": persisted.entities if persisted else None,
        "importance_score": persisted.importance_score if persisted else None,
        "event_time": persisted.event_time if persisted else None,
        "article_url": persisted.article_url if persisted else None,
        "citations": persisted.citations if persisted else None,
        "what_changed": persisted.what_changed if persisted else None,
        "short_summary": persisted.short_summary if persisted else None,
        "mock": (persisted.headline == "Mock Headline for TestCorp") if persisted else None,
        "article_persisted": bool(article_row),
        "image_url": persisted.image_url if persisted else None,
    }
    dump(report)
    db.close()
    return 0 if report["e2e"]["status"] == "VERIFIED" and report["schema"]["status"] == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
