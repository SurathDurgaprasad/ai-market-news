"""
Phase 1B, second attack pass, Area C (database integrity red team).

Explicit instruction for this area: "Do not assume transaction isolation
works because SQLite/WAL is enabled. Prove it." This file proves (or
disproves) isolation and rollback-scoping directly, against a real
file-backed SQLite engine configured identically to production
(app/db/session.py's PRAGMAs), not :memory:+StaticPool — see
test_concurrency_race.py's _file_backed_engine docstring for why
:memory:+StaticPool is unsafe for genuine multi-connection tests (it
hands every session the same raw sqlite3 connection object).
"""
from __future__ import annotations

import threading
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.source import Source
from app.models.article import Article
from app.models.event import Event, EventArticle
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.providers.llm import TestLLMProvider


def _file_backed_engine(tmp_path, name="db_integrity.db"):
    """
    Mirrors app/db/session.py's production SQLite PRAGMAs exactly
    (WAL, synchronous=NORMAL, busy_timeout, foreign_keys=ON) against a
    real temp-file database with normal per-connection pooling — the
    same pattern established in test_concurrency_race.py.
    """
    db_path = tmp_path / name
    db_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(db_engine, "connect")
    def _pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=db_engine)
    return db_engine


def test_uncommitted_write_is_invisible_to_a_concurrent_reader(tmp_path):
    """
    Direct proof, not an assumption: while a writer connection holds a
    flushed-but-not-yet-committed INSERT, a separate connection querying
    the same table must see ZERO rows. Only after COMMIT must the row
    become visible. If SQLite/WAL isolation were broken (a dirty read),
    the reader would observe the row during the uncommitted window.
    """
    engine = _file_backed_engine(tmp_path)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    flushed = threading.Event()
    release_commit = threading.Event()
    writer_done = threading.Event()

    def writer():
        db = SessionLocal()
        try:
            source = Source(name="Writer Source", url="https://writer.example.com/rss")
            db.add(source)
            db.flush()  # INSERT is pending in this connection's transaction, not committed
            flushed.set()
            release_commit.wait(timeout=10)
            db.commit()
        finally:
            db.close()
            writer_done.set()

    t = threading.Thread(target=writer)
    t.start()
    assert flushed.wait(timeout=10), "writer never reached the flushed-but-uncommitted state"

    # A separate connection must NOT see the uncommitted row.
    reader_before = SessionLocal()
    try:
        count_before = reader_before.query(Source).count()
    finally:
        reader_before.close()
    assert count_before == 0, (
        f"ISOLATION VIOLATION: a concurrent reader saw {count_before} row(s) "
        "from another connection's uncommitted transaction (dirty read)"
    )

    release_commit.set()
    assert writer_done.wait(timeout=10), "writer never finished committing"
    t.join(timeout=10)

    # After commit, the row must now be visible to a fresh connection.
    reader_after = SessionLocal()
    try:
        count_after = reader_after.query(Source).count()
    finally:
        reader_after.close()
    assert count_after == 1, (
        f"expected the committed row to become visible after commit, saw {count_after}"
    )

    engine.dispose()


def test_rollback_of_one_article_does_not_affect_an_earlier_committed_article(tmp_path):
    """
    Mirrors app/core/scheduler.py's real per-article loop: each
    process_article() call that succeeds ends with its own commit; a
    later article's failure triggers a rollback (scheduler.py's generic
    except-Exception handler). This proves that rollback only reverts the
    FAILED article's own uncommitted work, never an earlier, already
    -committed article/event from the same ingestion cycle — the
    behavior a shared, long-lived session across a whole source's article
    loop could plausibly get wrong if rollback scoping were broken.
    """
    engine = _file_backed_engine(tmp_path, name="rollback_scope.db")
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    source = Source(name="S", url="https://example.com/rss", type="rss", enabled=True)
    db.add(source)
    db.commit()
    source_id = source.id

    pipeline = IntelligencePipeline(db)
    pipeline.llm = TestLLMProvider()

    good_article = ArticleData(
        title="A perfectly normal article about an AI model release",
        url="https://example.com/good-article",
        content="This article contains enough characters to pass the minimum length validation used by the pipeline.",
    )
    good_event = pipeline.process_article(good_article, source_id)
    assert good_event is not None
    good_event_id = good_event.id
    # Committed by process_article itself (last_outcome == "created").
    assert pipeline.last_outcome == "created"

    # Simulate scheduler.py's per-article loop: force the NEXT article's
    # persist to fail after it has already staged (flushed) writes in the
    # SAME shared session, then roll back exactly like the real per-article
    # exception handler does.
    bad_article = ArticleData(
        title="A second, different article about a different AI model",
        url="https://example.com/bad-article",
        content="This article also contains enough characters to pass the minimum length validation check used here.",
    )
    # Directly stage a doomed write in the same session the way pipeline
    # internals would (flush without commit), then force the same
    # generic-exception + rollback path scheduler.py uses.
    doomed_article_row = Article(
        source_id=source_id,
        url="https://example.com/bad-article",
        title="doomed",
        raw_content="doomed content",
        hash="doomed-hash",
    )
    db.add(doomed_article_row)
    db.flush()  # pending, uncommitted — mirrors process_article's article-flush step
    try:
        raise RuntimeError("simulated failure after flush, before commit")
    except Exception:
        db.rollback()  # exactly what scheduler.py's per-article except-Exception does

    # The earlier, already-committed good article/event must be untouched.
    still_there_event = db.query(Event).filter(Event.id == good_event_id).first()
    assert still_there_event is not None
    assert still_there_event.headline == good_event.headline
    still_there_article = db.query(Article).filter(Article.url == good_article.url).first()
    assert still_there_article is not None

    # The doomed, rolled-back article must NOT have persisted.
    doomed_check = db.query(Article).filter(Article.url == "https://example.com/bad-article").first()
    assert doomed_check is None, "rollback failed to revert the doomed article's own uncommitted insert"

    db.close()
    engine.dispose()
