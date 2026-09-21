import pytest
from datetime import datetime, timedelta, timezone
from app.core.pipeline import IntelligencePipeline
from app.models.event import Event
from app.models.article import Article
from conftest import TestLLMProvider

def test_temporal_deduplication_horizon(db_session):
    # If an event occurred 4 days ago, and an update article arrives today,
    # it falls outside the 72-hour deduplication horizon.
    past_time = datetime.now(timezone.utc) - timedelta(days=4)
    
    from app.models.source import Source
    from uuid import uuid4
    test_source = Source(id=uuid4(), name="Test Source", url="http://test.com")
    db_session.add(test_source)
    
    # Create an old event manually
    old_event = Event(
        headline="Old Event",
        short_summary="Something happened 4 days ago.",
        event_time=past_time,
        importance_score=50,
        primary_source_id=test_source.id,
    )
    db_session.add(old_event)
    db_session.commit()
    
    # Ingest a new article that is semantically identical, but published today
    from app.core.parser import ArticleData
    article_data = ArticleData(
        title="Old Event Update",
        url="http://example.com/update",
        content="Something happened 4 days ago. This is an update.",
        published_at=datetime.now(timezone.utc),
    )
    
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = TestLLMProvider()
    
    event = pipeline.process_article(article_data, test_source.id)
    
    # The pipeline should create a NEW event because the old one is outside 
    # the 72-hour window.
    assert event is not None
    assert event.id != old_event.id
    assert pipeline.last_outcome == "created"

def test_temporal_out_of_order_backfill(db_session):
    # If we ingest an article from 5 days ago today, it gets its published_at
    # date. But when it checks for duplicates, the deduplication window is
    # based on datetime.now(timezone.utc) - 72 hours!
    # So it will NEVER find duplicates of itself if we re-ingest it!
    # Or rather, it won't deduplicate against other backfilled articles of the
    # same era because the horizon is absolute from NOW, not relative to the
    # article's published_at!
    
    from app.core.parser import ArticleData
    past_time = datetime.now(timezone.utc) - timedelta(days=5)
    
    article_data1 = ArticleData(
        title="Backfill Event",
        url="http://example.com/backfill1",
        content="We are backfilling data for testing purposes with enough characters to pass the fifty chars check.",
        published_at=past_time,
    )
    
    from app.models.source import Source
    from uuid import uuid4
    test_source = Source(id=uuid4(), name="Test Source 2", url="http://test2.com")
    db_session.add(test_source)
    db_session.commit()
    
    pipeline1 = IntelligencePipeline(db_session, llm_env="test")
    pipeline1.llm = TestLLMProvider()
    event1 = pipeline1.process_article(article_data1, test_source.id)
    
    assert event1 is not None
    assert pipeline1.last_outcome == "created"
    
    # Now ingest a second article about the SAME event, also from 5 days ago, with slightly different content to bypass hash check
    article_data2 = ArticleData(
        title="Backfill Event",
        url="http://example.com/backfill2", # Different URL
        content="We are backfilling data for testing purposes with enough characters to pass the fifty chars check! Extra bit here.",
        published_at=past_time,
    )
    
    pipeline2 = IntelligencePipeline(db_session, llm_env="test")
    pipeline2.llm = TestLLMProvider()
    event2 = pipeline2.process_article(article_data2, test_source.id)
    
    # Because find_semantic_match uses `datetime.now(timezone.utc) - 72h`,
    # it will NOT see event1 (which has event_time = past_time)!
    # Thus it will create a DUPLICATE canonical event!
    assert event2 is not None
    assert event2.id != event1.id
    assert pipeline2.last_outcome == "created"
    
    # This is a KNOWN LIMITATION: historical backfilling produces duplicates
    # because the deduplication horizon is anchored to wall-clock NOW, not
    # the article's time.
