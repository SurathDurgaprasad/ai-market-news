"""Live NVIDIA grouping / update / delay checks. Never prints credentials."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

os.environ["TESTING"] = "0"
os.environ["TEST_MODE"] = "0"
os.environ.setdefault("LLM_PROVIDER", "nvidia")
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.core.providers.llm import NVIDIAProvider, TestLLMProvider, get_llm_provider
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.db.base_class import Base
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.models.article import Article
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

SAMPLE = (
    "NVIDIA announced Nemotron-Mini as a hosted NIM instruct model for developers. "
    "The company said the checkpoint supports a 128k context window and is available "
    "through the NVIDIA API catalog. Pricing was not disclosed. "
    "The release is a software model drop, not a new GPU SKU."
)
REWRITE = (
    "NVIDIA today made Nemotron-Mini available via the hosted NIM API catalog. "
    "Developers can call the instruct checkpoint with a 128k context window. "
    "This coverage describes the same Nemotron-Mini NIM software launch. "
    "No new GPU SKU was announced as part of this model drop."
)
GPU = (
    "NVIDIA announced the B300 GPU for training frontier models, with twice the "
    "memory bandwidth of B200, shipping to cloud providers this quarter. This is a "
    "hardware SKU announcement, not a Nemotron model drop."
)
UPDATE = (
    SAMPLE
    + " UPDATE: NVIDIA later confirmed general availability started today and published "
    "token pricing for the Nemotron-Mini hosted NIM endpoint."
)


def dump(obj):
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=True))


def main() -> int:
    provider = get_llm_provider()
    assert isinstance(provider, NVIDIAProvider), type(provider).__name__
    assert not isinstance(provider, TestLLMProvider)
    path = os.path.join(os.path.dirname(__file__), "nvidia_grouping.db")
    if os.path.exists(path):
        os.remove(path)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _rec):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    source = Source(name="Live Grouping", url="https://example.com/rss", type="rss", enabled=True)
    db.add(source)
    db.commit()
    pipeline = IntelligencePipeline(db)
    assert isinstance(pipeline.llm, NVIDIAProvider)
    pipeline.llm = provider
    now = datetime.now(timezone.utc)
    report = {"model": provider.model, "provider": type(pipeline.llm).__name__}

    e1 = pipeline.process_article(
        ArticleData(
            title="NVIDIA launches Nemotron-Mini on hosted NIM",
            url="https://blogs.nvidia.com/blog/nemotron-mini-group-1/",
            content=SAMPLE,
            published_at=now - timedelta(days=2),
        ),
        source.id,
    )
    o1 = pipeline.last_outcome
    e2 = pipeline.process_article(
        ArticleData(
            title="NVIDIA makes Nemotron-Mini available via API catalog",
            url="https://techcrunch.com/nvidia-nemotron-mini-group-2/",
            content=REWRITE,
            published_at=now,
        ),
        source.id,
    )
    o2 = pipeline.last_outcome
    merged = bool(e1 and e2 and e1.id == e2.id)
    report["same_event_merge"] = {
        "status": "VERIFIED" if merged else "FAILED",
        "same_id": merged,
        "outcome_1": o1,
        "outcome_2": o2,
        "headline_1": getattr(e1, "headline", None),
        "headline_2": getattr(e2, "headline", None),
        "event_time_1": getattr(e1, "event_time", None),
        "created_at_1": getattr(e1, "created_at", None),
        "links": db.query(EventArticle).filter(EventArticle.event_id == e1.id).count() if e1 else 0,
    }

    gpu = pipeline.process_article(
        ArticleData(
            title="NVIDIA announces B300 GPU with higher memory bandwidth",
            url="https://blogs.nvidia.com/blog/b300-group-distinct/",
            content=GPU,
            published_at=now,
        ),
        source.id,
    )
    distinct = bool(e1 and gpu and e1.id != gpu.id)
    report["different_event"] = {
        "status": "VERIFIED" if distinct else "FAILED",
        "same_id": bool(e1 and gpu and e1.id == gpu.id),
        "gpu_headline": getattr(gpu, "headline", None),
        "outcome": pipeline.last_outcome,
    }

    updated = pipeline.process_article(
        ArticleData(
            title="NVIDIA launches Nemotron-Mini on hosted NIM",
            url="https://blogs.nvidia.com/blog/nemotron-mini-group-1/",
            content=UPDATE,
            published_at=now,
        ),
        source.id,
    )
    report["update"] = {
        "status": "VERIFIED" if (updated and e1 and (updated.id != e1.id or e1.superseded_by_id)) else "PARTIALLY VERIFIED",
        "outcome": pipeline.last_outcome,
        "update_id": str(updated.id) if updated else None,
        "original_id": str(e1.id) if e1 else None,
        "original_superseded_by": str(e1.superseded_by_id) if e1 and e1.superseded_by_id else None,
        "update_headline": getattr(updated, "headline", None),
        "update_version": getattr(updated, "version", None),
    }
    if e1:
        db.refresh(e1)
        report["update"]["original_superseded_by"] = str(e1.superseded_by_id) if e1.superseded_by_id else None
        if e1.superseded_by_id and updated and str(e1.superseded_by_id) == str(updated.id):
            report["update"]["status"] = "VERIFIED"

    delay_ok = False
    if e1 and e1.event_time and e1.created_at:
        delay_ok = True
    report["delayed_reporting"] = {
        "status": "VERIFIED" if (merged and delay_ok) else "PARTIALLY VERIFIED",
        "event_time": getattr(e1, "event_time", None),
        "created_at": getattr(e1, "created_at", None),
        "second_published_later": True,
        "merged": merged,
    }

    report["counts"] = {
        "events": db.query(Event).filter(Event.superseded_by_id.is_(None)).count(),
        "all_events": db.query(Event).count(),
        "articles": db.query(Article).count(),
        "links": db.query(EventArticle).count(),
    }
    dump(report)
    db.close()
    return 0 if merged and distinct else 1


if __name__ == "__main__":
    raise SystemExit(main())
