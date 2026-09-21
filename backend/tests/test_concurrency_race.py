import pytest
import threading
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base_class import Base
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.models.article import Article
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.providers.llm import TestLLMProvider

def test_concurrent_same_event_different_urls():
    # Setup in-memory SQLite with threading support
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    db = SessionLocal()
    source = Source(name="Test Source", url="http://test.com")
    db.add(source)
    db.commit()
    source_id = source.id
    db.close()

    # We will simulate two threads processing two different URLs of the SAME event.
    article_a = ArticleData(
        title="GPT-6 Released",
        url="http://site-a.com/gpt6",
        content="OpenAI released GPT-6 today. duplicate_trigger"
    )
    article_b = ArticleData(
        title="OpenAI launches GPT-6",
        url="http://site-b.com/gpt6",
        content="GPT-6 is out. duplicate_trigger"
    )
    
    # We will inject a delay in the LLM summarize call to force the race condition
    class DelayedTestLLMProvider(TestLLMProvider):
        def summarize_event(self, content):
            time.sleep(0.5)
            return super().summarize_event(content)

    def worker_process(article_data, result_container, index):
        db = SessionLocal()
        pipeline = IntelligencePipeline(db, llm_env="test")
        pipeline.llm = DelayedTestLLMProvider() # Override LLM to inject delay
        event = pipeline.process_article(article_data, source_id)
        if event:
            result_container[index] = event.id
        db.close()

    results = [None, None]
    
    t1 = threading.Thread(target=worker_process, args=(article_a, results, 0))
    t2 = threading.Thread(target=worker_process, args=(article_b, results, 1))
    
    t1.start()
    t2.start()
    
    t1.join()
    t2.join()

    # Check the database for events
    db = SessionLocal()
    events = db.query(Event).all()
    db.close()
    
    # If the system is robust against concurrent insertion, there should be exactly ONE event.
    # If it's vulnerable to the race condition, there will be TWO events.
    assert len(events) == 1, f"Concurrency failure: {len(events)} duplicate canonical events were created!"
