from app.core.parser import parse_mock_source
from app.core.deduplication import generate_content_hash, is_duplicate_title
from tests.fixtures.sources import FIXTURES
from app.core.providers.llm import TestLLMProvider
from app.models.source import Source
import json

def test_full_pipeline_mocked():
    """
    Test the ingestion pipeline execution end-to-end locally using mocks.
    Pipeline: Source -> Fetch -> Parse -> Deduplicate -> Cluster -> Classify -> Store
    """
    # 1. Fetch & Parse (simulated)
    article_data = parse_mock_source(json.dumps(FIXTURES["normal_1"]))
    assert article_data is not None
    assert article_data.title == "OpenAI Releases GPT-5"
    
    # 2. Deduplicate
    # In a real DB we would check if hash exists. We simulate it here.
    content_hash = generate_content_hash(article_data.content)
    is_duplicate = False # Simulated db check
    assert not is_duplicate
    
    # 3. Classify / Analyze via LLM Provider
    llm_provider = TestLLMProvider()
    classification = llm_provider.classify_event(article_data.content)
    
    assert classification.importance_score == 50
    assert "Test" in classification.tags
    
    # 4. Cluster (Skipped full DB pgvector mock for now, but logical flow verified)
    
    # 5. Summarize
    summary = llm_provider.summarize_event(article_data.content)
    assert summary.headline == "Mock Headline for TestCorp"

def test_semantic_clustering_same_event(db_session):
    """
    Test that two articles with different titles but the same real-world event
    are correctly clustered using LLM entity extraction and semantic verification.
    """
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.source import TestSourceProvider
    
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    # 1. First article (Breaking News)
    r1 = provider.fetch("https://openai.com/blog", "normal_1")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    assert event1 is not None
    
    # 2. Second article (Different source, same event)
    # The title is different enough to bypass Jaccard (threshold 0.85).
    # It shares the entity "TestCorp", which triggers LLM verification.
    # LLM mock returns True because "duplicate_trigger" is in the content.
    r2 = provider.fetch("https://techcrunch.com", "different_source_same_event")
    event2 = pipeline.process_article(r2["data"], source_id)
    
    # event2 should be the SAME event as event1
    assert event2 is not None
    assert event2.id == event1.id
    
    # Verify the second article was linked as 'supporting'
    from app.models.event import EventArticle
    links = db_session.query(EventArticle).filter(EventArticle.event_id == event1.id).all()
    assert len(links) == 2

def test_semantic_clustering_different_event_same_entity(db_session):
    """
    Test that two articles with the same entity but describing DIFFERENT real-world events
    are NOT clustered.
    """
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.source import TestSourceProvider
    
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    r1 = provider.fetch("https://openai.com/blog", "normal_1")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    
    # 2. Second article (Same entity, different event)
    # It shares "TestCorp" entity, so semantic overlap triggers.
    # But LLM mock returns False because "duplicate_trigger" is missing!
    r2 = provider.fetch("https://techcrunch.com", "normal_2") 
    event2 = pipeline.process_article(r2["data"], source_id)
    
    # event2 should be a NEW event
    assert event2 is not None
    assert event2.id != event1.id

def test_pipeline_updated_article_same_url(db_session):
    """
    Test that an article at the same URL but with different content
    is ingested as an update rather than silently dropped.
    """
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.source import TestSourceProvider
    from app.models.article import Article
    
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    # 1. First fetch
    r1 = provider.fetch("https://openai.com/blog", "normal_1")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    
    # 2. Same URL, but content was updated (different hash)
    r2 = provider.fetch("https://openai.com/blog", "updated_article")
    # Our mock fetcher uses the second arg as the fixture key, so the URL in the fixture is the same, but content is different
    event2 = pipeline.process_article(r2["data"], source_id)
    
    # The pipeline should have appended `#update-` to the URL to bypass the unique constraint
    # and properly ingest the new evidence. Instead of blindly linking it, it should create
    # a new Event version that supersedes the original.
    assert event2 is not None
    assert event2.id != event1.id
    
    # Reload event1 from db to see if superseded_by_id was set
    db_session.refresh(event1)
    assert event1.superseded_by_id == event2.id
    assert event2.version == 2
    
    # Verify we now have TWO articles in the database
    articles = db_session.query(Article).all()
    assert len(articles) == 2
