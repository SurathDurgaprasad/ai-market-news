"""Ingest several unseen real RSS articles via NVIDIA into production SQLite."""
from __future__ import annotations

import json
import os
import sys

os.environ["TESTING"] = "0"
os.environ["TEST_MODE"] = "0"
os.environ.setdefault("LLM_PROVIDER", "nvidia")
sys.path.insert(0, os.path.dirname(__file__))

from app.core.providers.llm import NVIDIAProvider, TestLLMProvider, get_llm_provider
from app.core.pipeline import IntelligencePipeline
from app.core.parser import parse_rss_feed
from app.core.fetcher import fetch_url
from app.core.deduplication import normalize_url
from app.db.session import SessionLocal
from app.models.source import Source
from app.models.event import Event
from app.models.article import Article


def dump(obj):
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=True))


def main() -> int:
    provider = get_llm_provider()
    if not isinstance(provider, NVIDIAProvider) or isinstance(provider, TestLLMProvider):
        dump({"status": "FAILED", "provider": type(provider).__name__})
        return 2
    if getattr(provider, "model", None) != "openai/gpt-oss-20b":
        dump({"status": "FAILED", "model": getattr(provider, "model", None)})
        return 2

    db = SessionLocal()
    leftover = db.query(Source).filter(Source.name.like("Sched %")).all()
    for source in leftover:
        db.delete(source)
    db.commit()

    existing_urls = {normalize_url(a.url) for a in db.query(Article).all() if a.url}
    pipeline = IntelligencePipeline(db)
    if isinstance(pipeline.llm, TestLLMProvider):
        dump({"status": "FAILED", "pipeline": type(pipeline.llm).__name__})
        return 2
    pipeline.llm = provider

    results = []
    wanted = 4
    sources = (
        db.query(Source)
        .filter(Source.enabled == True, Source.type.in_(("rss", "RSS")))  # noqa: E712
        .all()
    )
    for source in sources:
        feed_url = source.url
        if len(results) >= wanted:
            break
        try:
            items = parse_rss_feed(fetch_url(feed_url).text)
        except Exception as exc:
            print("FEED_FAIL", feed_url, type(exc).__name__)
            continue
        for item in items:
            if len(results) >= wanted:
                break
            url = normalize_url(item.url)
            if not url or url in existing_urls:
                continue
            existing_urls.add(url)
            try:
                event = pipeline.process_article(item, source.id)
            except Exception as exc:
                row = {
                    "rss_title": item.title,
                    "rss_url": item.url,
                    "outcome": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "provider": type(pipeline.llm).__name__,
                    "mock": False,
                }
                results.append(row)
                print("INGEST", json.dumps(row, default=str, ensure_ascii=True))
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            db.expire_all()
            persisted = db.query(Event).filter(Event.id == event.id).first() if event else None
            row = {
                "rss_title": item.title,
                "rss_url": item.url,
                "published_at": item.published_at,
                "outcome": pipeline.last_outcome,
                "json_mode": provider._json_mode,
                "event_id": str(persisted.id) if persisted else None,
                "headline": persisted.headline if persisted else None,
                "entities": persisted.entities if persisted else None,
                "importance_score": persisted.importance_score if persisted else None,
                "event_time": persisted.event_time if persisted else None,
                "article_url": persisted.article_url if persisted else None,
                "citations": persisted.citations if persisted else None,
                "source": source.name,
                "mock": (persisted.headline == "Mock Headline for TestCorp") if persisted else False,
                "provider": type(pipeline.llm).__name__,
            }
            results.append(row)
            print("INGEST", json.dumps(row, default=str, ensure_ascii=True))

    dump(
        {
            "provider": type(pipeline.llm).__name__,
            "model": provider.model,
            "is_test": isinstance(pipeline.llm, TestLLMProvider),
            "ingested": len(results),
            "created": sum(1 for r in results if r.get("outcome") == "created"),
            "linked": sum(1 for r in results if r.get("outcome") == "linked"),
            "results": results,
        }
    )
    db.close()
    created_or_linked = [r for r in results if r.get("outcome") in ("created", "linked") and not r.get("mock")]
    return 0 if created_or_linked else 1


if __name__ == "__main__":
    raise SystemExit(main())
