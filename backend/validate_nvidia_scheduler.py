"""Controlled scheduler isolation check with NVIDIA. Never prints credentials.

Uses an isolated SQLite file so synthetic scheduler sources never land in
the production ai_platform.db.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ["TESTING"] = "0"
os.environ["TEST_MODE"] = "0"
os.environ.setdefault("LLM_PROVIDER", "nvidia")
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.providers.llm import NVIDIAProvider, TestLLMProvider, get_llm_provider
from app.core.parser import ArticleData
from app.core.scheduler import IngestionScheduler
from app.db.base_class import Base
from app.models.source import Source
from app.models.event import Event
from app.models.article import Article  # noqa: F401 — register metadata
from app.models.event import EventArticle  # noqa: F401


def main() -> int:
    provider = get_llm_provider()
    assert isinstance(provider, NVIDIAProvider)
    assert not isinstance(provider, TestLLMProvider)

    path = os.path.join(os.path.dirname(__file__), "nvidia_scheduler.db")
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
    IsolatedSession = sessionmaker(bind=engine, expire_on_commit=False)

    db = IsolatedSession()
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    good = Source(
        name=f"Sched Good {stamp}",
        url=f"https://huggingface.co/blog/feed.xml?sched={stamp}",
        type="rss",
        enabled=True,
        last_fetch_at=None,
    )
    bad = Source(
        name=f"Sched Broken {stamp}",
        url=f"https://this-source-does-not-exist-{stamp}.invalid/rss",
        type="rss",
        enabled=True,
        last_fetch_at=None,
    )
    db.add_all([good, bad])
    db.commit()
    good_id, bad_id = good.id, bad.id
    db.close()

    article = ArticleData(
        title="Scheduler NVIDIA ingest of a hosted instruct model",
        url=f"https://huggingface.co/blog/sched-nvidia-live-{stamp}",
        content=(
            "Hugging Face published a blog post describing a hosted instruct model with a "
            "documented 128k context window for developers. This article is long enough to "
            "pass the minimum content gate used by the ingestion pipeline."
        ),
        published_at=datetime.now(timezone.utc),
    )

    captured = []
    from app.core.pipeline import IntelligencePipeline

    class Capture(IntelligencePipeline):
        def __init__(self, db, llm_env=None):
            super().__init__(db, llm_env=llm_env)
            captured.append(self)

    def fake_fetch(url: str):
        if ".invalid" in url:
            raise RuntimeError("source fetch failed")
        resp = MagicMock()
        resp.text = "<rss><channel></channel></rss>"
        return resp

    def fake_parse(_text: str):
        return [article]

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", IsolatedSession):
        with patch("app.core.pipeline.IntelligencePipeline", Capture):
            with patch("app.core.fetcher.fetch_url", side_effect=fake_fetch):
                with patch("app.core.parser.parse_rss_feed", side_effect=fake_parse):
                    scheduler.run_ingestion_cycle()

    db = IsolatedSession()
    good_row = db.query(Source).filter(Source.id == good_id).first()
    bad_row = db.query(Source).filter(Source.id == bad_id).first()
    print("captured", len(captured))
    print("provider", type(captured[0].llm).__name__ if captured else None)
    print("is_test", bool(captured) and isinstance(captured[0].llm, TestLLMProvider))
    print("good_health", good_row.health_status if good_row else None)
    print("good_summary", good_row.last_ingest_summary if good_row else None)
    print("bad_health", bad_row.health_status if bad_row else None)
    print("bad_error", (bad_row.last_error_info or "")[:80] if bad_row else None)
    print("isolated", bool(bad_row and bad_row.health_status == "failing" and good_row and good_row.health_status in ("healthy", "degraded")))
    mock_headlines = [e.headline for e in db.query(Event).all() if e.headline == "Mock Headline for TestCorp"]
    print("mock_headlines", len(mock_headlines))
    print("isolated_db", path)
    db.close()
    if not captured or isinstance(captured[0].llm, TestLLMProvider):
        return 1
    if not (bad_row and bad_row.health_status == "failing"):
        return 1
    if not (good_row and good_row.health_status in ("healthy", "degraded")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
