"""
End-to-end pipeline tests using the in-memory SQLite database (conftest db_session fixture).

Verifies the full article → event creation path including:
- entity and event_time propagation
- article_url cleanliness (no #update- fragments)
- deduplication
- prompt injection filtering
- concurrent ingestion safety
"""
import pytest
import threading
from app.core.pipeline import IntelligencePipeline
from app.core.providers.source import TestSourceProvider
from app.models.source import Source
from app.models.article import Article
from app.models.event import Event


def test_pipeline_normal_article(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()

    response = provider.fetch("https://openai.com/blog/rss.xml", "normal_1")
    assert response["status"] == 200

    source = db_session.query(Source).first()
    event = pipeline.process_article(response["data"], source.id)

    assert event is not None
    assert event.headline == "Mock Headline for TestCorp"
    assert event.importance_score == 50
    assert db_session.query(Article).count() == 1
    assert db_session.query(Event).count() == 1


def test_pipeline_stores_entities_from_classification(db_session):
    """
    Entities extracted during LLM classification must be persisted on the Event.
    Previously they were computed and thrown away.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    response = provider.fetch("url", "normal_1")
    event = pipeline.process_article(response["data"], source.id)

    assert event is not None
    # TestLLMProvider.classification_fixture has entities=["TestCorp"]
    assert event.entities is not None
    assert "TestCorp" in event.entities


def test_pipeline_stores_event_time_from_published_at(db_session):
    """
    The Event.event_time must be set from the article's published_at, not None.
    This lets cards display when the event occurred, not when it was ingested.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    # normal_1 fixture has published_at="2026-09-17T10:00:00Z"
    response = provider.fetch("url", "normal_1")
    event = pipeline.process_article(response["data"], source.id)

    assert event is not None
    # event_time must be populated from Article.published_at
    assert event.event_time is not None


def test_pipeline_article_url_is_clean_after_same_url_update(db_session):
    """
    When a same-URL article is updated, the pipeline appends #update-<hash> to the
    stored Article URL for deduplication. The canonical Event.article_url used for
    the 'Official Source' button must NOT contain this fragment.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    # First ingestion
    res1 = provider.fetch("url", "normal_1")
    event1 = pipeline.process_article(res1["data"], source.id)
    assert event1 is not None

    # Same URL, updated content → creates a new versioned event
    res2 = provider.fetch("url", "updated_article")
    event2 = pipeline.process_article(res2["data"], source.id)
    assert event2 is not None

    # The new event's article_url must be clean (no #update- fragment)
    assert event2.article_url is not None
    assert "#update-" not in event2.article_url


def test_pipeline_duplicate_url(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    res1 = provider.fetch("url", "normal_1")
    pipeline.process_article(res1["data"], source.id)

    res2 = provider.fetch("url", "duplicate_exact")
    event2 = pipeline.process_article(res2["data"], source.id)

    assert event2 is None
    assert db_session.query(Article).count() == 1


def test_pipeline_prompt_injection(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    res = provider.fetch("url", "prompt_injection")
    event = pipeline.process_article(res["data"], source.id)

    # Pipeline should reject due to importance_score == 0 from injection detection
    assert event is None
    assert db_session.query(Event).count() == 0


def test_pipeline_rejects_javascript_url(db_session):
    """
    Security test (adversarial #17): An article with a javascript: URL in its link field
    must be completely rejected by the pipeline — it must not reach the database or
    the frontend where it could be rendered as an XSS vector in the 'Official Source' button.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    res = provider.fetch("url", "malicious_javascript_url")
    event = pipeline.process_article(res["data"], source.id)

    # The javascript: URL must be normalized to "" by normalize_url(), causing the
    # pipeline to return None at the "not url" check.
    assert event is None
    assert db_session.query(Article).count() == 0


def test_pipeline_rejects_data_uri_url(db_session):
    """
    Security test: A data: URI in an article link must also be rejected.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    res = provider.fetch("url", "malicious_data_url")
    event = pipeline.process_article(res["data"], source.id)

    assert event is None
    assert db_session.query(Article).count() == 0


def test_pipeline_multi_update_same_url_does_not_orphan_versions(db_session):
    """
    Regression: when an RSS feed publishes two update snippets for the same article
    in the same batch (same base URL, different content), the pipeline must produce
    exactly ONE live (unsuperseded) event. The earlier update event must be
    superseded by the later one, not left as a live orphan.

    This mirrors the Hugging Face blog pattern where #update-<hash> fragments are
    stripped to the same canonical URL, causing both updates to be detected as
    successive changes to the same original article.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    # Original article
    res1 = provider.fetch("url", "normal_1")
    event1 = pipeline.process_article(res1["data"], source.id)
    assert event1 is not None

    # First update (content changed)
    res2 = provider.fetch("url", "updated_article")
    event2 = pipeline.process_article(res2["data"], source.id)
    assert event2 is not None
    assert event2.id != event1.id

    # Second update from the SAME base URL in the same batch
    res3 = provider.fetch("url", "updated_article_v2")
    event3 = pipeline.process_article(res3["data"], source.id)
    assert event3 is not None

    # Exactly ONE event must be live (unsuperseded)
    live_events = db_session.query(Event).filter(Event.superseded_by_id.is_(None)).all()
    assert len(live_events) == 1, (
        f"Expected 1 live event, got {len(live_events)}: "
        f"{[(e.headline, str(e.id)[:8]) for e in live_events]}"
    )
    assert live_events[0].id == event3.id


def test_pipeline_different_source_same_event(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    res1 = provider.fetch("url", "normal_1")
    pipeline.process_article(res1["data"], source.id)

    # "different_source_same_event" has a similar title and "duplicate_trigger"
    # so the Jaccard dedup AND the LLM entity+semantic check both fire
    res2 = provider.fetch("url", "different_source_same_event")
    event2 = pipeline.process_article(res2["data"], source.id)

    assert db_session.query(Event).count() == 1
    assert event2 is not None


def test_pipeline_concurrent_duplicate_ingestion():
    """
    Adversarial test #19: Two workers try to ingest the exact same article simultaneously.
    Expected outcome:
    - Exactly ONE Article record in the database
    - Exactly ONE Event record in the database
    - The pipeline's IntegrityError handler gracefully returns None for the loser
    - No corruption, no rollback of the winner's data

    Uses a file-based SQLite database so each worker thread gets its own connection
    (required for real concurrent access — StaticPool/in-memory shares one connection
    which is not thread-safe for concurrent writes).
    """
    import os
    import tempfile
    import uuid as uuid_lib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base_class import Base as _Base
    from app.models.source import Source as _Source

    # Create a temp SQLite file (deleted in the finally block)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(tmp_fd)

    try:
        c_engine = create_engine(
            f"sqlite:///{tmp_path}",
            connect_args={"check_same_thread": False},
        )
        _Base.metadata.create_all(bind=c_engine)
        CSession = sessionmaker(bind=c_engine, autocommit=False, autoflush=False)

        # Seed a source
        setup_db = CSession()
        src = _Source(id=uuid_lib.uuid4(), name="Concurrent Source",
                      url="https://concurrent.example.com", type="rss", tier="primary")
        setup_db.add(src)
        setup_db.commit()
        source_id = src.id
        setup_db.close()

        results = []
        errors = []

        def worker():
            db = CSession()
            try:
                p = IntelligencePipeline(db)
                provider = TestSourceProvider()
                res = provider.fetch("url", "normal_1")
                evt = p.process_article(res["data"], source_id)
                results.append(evt)
            except Exception as exc:
                errors.append(exc)
            finally:
                db.close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Neither worker should surface an unhandled exception
        assert len(errors) == 0, f"Unexpected unhandled errors: {errors}"

        # Exactly one article and one event despite concurrent attempts
        verify_db = CSession()
        article_count = verify_db.query(Article).count()
        event_count = verify_db.query(Event).count()
        verify_db.close()

        assert article_count == 1, f"Expected 1 article after concurrent ingestion, got {article_count}"
        assert event_count == 1, f"Expected 1 event after concurrent ingestion, got {event_count}"

    finally:
        _Base.metadata.drop_all(bind=c_engine)
        c_engine.dispose()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
