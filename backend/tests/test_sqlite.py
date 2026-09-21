"""SQLite product-database tests. PostgreSQL is not used."""
from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.source import Source
from app.models.article import Article
from app.models.event import Event, EventArticle
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.providers.llm import TestLLMProvider


def _sqlite_session(path: str):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _rec):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return engine, Session


def test_sqlite_is_product_database():
    from app.core.config import settings
    assert settings.get_database_url().startswith("sqlite")


def test_sqlite_duplicate_url_integrity_and_rollback():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        engine, Session = _sqlite_session(path)
        db = Session()
        source = Source(name="S", url="https://example.com/rss", type="rss", enabled=True)
        db.add(source)
        db.commit()
        a1 = Article(source_id=source.id, url="https://example.com/a", title="One", hash="h1")
        db.add(a1)
        db.commit()
        a2 = Article(source_id=source.id, url="https://example.com/a", title="Two", hash="h2")
        db.add(a2)
        try:
            db.commit()
            assert False, "duplicate URL must raise IntegrityError"
        except IntegrityError:
            db.rollback()
        assert db.query(Article).count() == 1
        db.close()
        engine.dispose()
    finally:
        os.unlink(path)


def test_sqlite_event_article_relationship_and_restart():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        engine, Session = _sqlite_session(path)
        db = Session()
        source = Source(name="S", url="https://example.com/rss", type="rss", enabled=True)
        db.add(source)
        db.commit()
        event = Event(
            headline="Canonical",
            short_summary="Summary",
            importance_score=70,
            entities=["NVIDIA"],
            primary_source_id=source.id,
            article_url="https://example.com/a",
            event_time=datetime(2026, 9, 18, tzinfo=timezone.utc),
        )
        article = Article(source_id=source.id, url="https://example.com/a", title="A", hash="h")
        db.add(event)
        db.add(article)
        db.flush()
        db.add(EventArticle(event_id=event.id, article_id=article.id, link_type="primary"))
        db.commit()
        event_id = str(event.id)
        db.close()
        engine.dispose()

        engine2, Session2 = _sqlite_session(path)
        db2 = Session2()
        restored = db2.query(Event).filter(Event.headline == "Canonical").first()
        assert restored is not None
        assert str(restored.id) == event_id
        assert db2.query(EventArticle).count() == 1
        db2.close()
        engine2.dispose()
    finally:
        os.unlink(path)


def test_sqlite_wal_and_concurrent_readers(tmp_path):
    path = str(tmp_path / "wal.sqlite3")
    engine, Session = _sqlite_session(path)
    db = Session()
    db.add(Source(name="S", url="https://example.com/rss", type="rss"))
    db.commit()
    mode = db.execute(text("PRAGMA journal_mode")).scalar()
    assert str(mode).lower() == "wal"
    db.close()

    def read(_i):
        s = Session()
        try:
            return s.query(Source).count()
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(read, range(8)))
    assert counts == [1] * 8
    engine.dispose()


def test_sqlite_pipeline_duplicate_article(db_session):
    pipeline = IntelligencePipeline(db_session)
    pipeline.llm = TestLLMProvider()
    source_id = db_session.query(Source).first().id
    article = ArticleData(
        title="A long enough headline about an AI model",
        url="https://example.com/unique-dup",
        content="This article contains enough characters to pass the minimum length validation check used by the pipeline.",
    )
    first = pipeline.process_article(article, source_id)
    second = pipeline.process_article(article, source_id)
    assert first is not None
    assert second is None
    assert pipeline.last_outcome == "duplicate"
    assert db_session.query(Event).count() == 1
    assert db_session.query(Article).count() == 1


def test_pipeline_summarizes_before_sqlite_write(db_session):
    """NVIDIA/LLM work must finish before the article INSERT holds a SQLite write lock."""
    from sqlalchemy import event as sa_event

    order = []

    @sa_event.listens_for(db_session, "after_flush")
    def _on_flush(session, _ctx):
        if any(isinstance(obj, Article) for obj in session.new):
            order.append("article_flush")

    class Probe(TestLLMProvider):
        def classify_event(self, content):
            order.append("classify")
            return super().classify_event(content)

        def summarize_event(self, content):
            order.append("summarize")
            return super().summarize_event(content)

    pipeline = IntelligencePipeline(db_session)
    pipeline.llm = Probe()
    source_id = db_session.query(Source).first().id
    article = ArticleData(
        title="A long enough headline about an AI model",
        url="https://example.com/summarize-before-write",
        content="This article contains enough characters to pass the minimum length validation check used by the pipeline.",
    )
    event = pipeline.process_article(article, source_id)
    assert event is not None
    assert order.index("summarize") < order.index("article_flush")
