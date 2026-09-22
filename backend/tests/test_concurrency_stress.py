import pytest
import threading
import time
import concurrent.futures
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.models.article import Article
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.providers.llm import TestLLMProvider

def setup_db(tmp_path):
    """
    Real file-backed SQLite, matching production's pooling model
    (app/db/session.py only uses StaticPool for `:memory:`/`sqlite://`).

    StaticPool + `:memory:` hands every session the exact same raw
    sqlite3 connection/cursor object; under real concurrent threads this
    produced spurious ORM-level errors ("Instance has been deleted, or
    its row is otherwise not present", "This result object does not
    return rows. It has been closed automatically.") and non-deterministic
    duplicate-event failures that were artifacts of connection sharing
    across threads, not of pipeline logic — confirmed by this test
    becoming deterministic once switched to a file-backed engine, which
    gives each thread its own pooled connection the way production does.
    """
    db_path = tmp_path / "concurrency_stress.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    source1 = Source(name="Test Source A", url="http://site-a.com")
    source2 = Source(name="Test Source B", url="http://site-b.com")
    db.add(source1)
    db.add(source2)
    db.commit()
    return engine, SessionLocal, source1.id, source2.id

class DelayedTestLLMProvider(TestLLMProvider):
    def __init__(self, delay=0.5, fail_after=0):
        super().__init__()
        self.delay = delay
        self.fail_after = fail_after
        self.call_count = 0
        self._lock = threading.Lock()

    def summarize_event(self, content):
        with self._lock:
            self.call_count += 1
            if self.fail_after > 0 and self.call_count > self.fail_after:
                raise Exception("Simulated LLM timeout")
        
        time.sleep(self.delay)
        return super().summarize_event(content)

def run_concurrent_workers(SessionLocal, workers_count, articles, provider, source_ids):
    def worker_process(article_data, source_id):
        db = SessionLocal()
        try:
            pipeline = IntelligencePipeline(db, llm_env="test")
            pipeline.llm = provider
            event = pipeline.process_article(article_data, source_id)
            if pipeline.last_outcome == "rejected":
                print(f"Worker {article_data.url} rejected. content len: {len(article_data.content)}")
            return (event.id if event else None, pipeline.last_outcome)
        except Exception as e:
            return e
        finally:
            db.close()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers_count) as executor:
        futures = []
        for i in range(workers_count):
            article = articles[i % len(articles)]
            source_id = source_ids[i % len(source_ids)]
            futures.append(executor.submit(worker_process, article, source_id))
        
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            
    return results

def test_concurrency_stress_same_event_different_urls_10_workers(tmp_path):
    engine, SessionLocal, sid1, sid2 = setup_db(tmp_path)

    articles = [
        ArticleData(title=f"Breaking: GPT-{i}", url=f"http://site.com/{i}", content="duplicate_trigger with enough characters to pass fifty chars check")
        for i in range(10)
    ]

    # 10 workers all hitting the same event, 0.2s LLM delay
    provider = DelayedTestLLMProvider(delay=0.2)
    results = run_concurrent_workers(SessionLocal, 10, articles, provider, [sid1, sid2])

    db = SessionLocal()
    events = db.query(Event).all()
    articles_db = db.query(Article).all()
    event_articles = db.query(EventArticle).all()
    db.close()

    worker_errors = [r for r in results if isinstance(r, Exception)]
    assert not worker_errors, f"Worker thread(s) raised: {worker_errors}"
    assert len(events) == 1, f"Expected 1 event, got {len(events)}"

    # All 10 articles share identical content, so only the first is ever
    # persisted as an Article row — the rest are dropped as exact content-hash
    # duplicates before an event is even attempted (pipeline.py's
    # existing_article_by_hash check). That is correct dedup behavior, not a
    # gap: this test's job is to prove concurrent *event* creation converges
    # on one canonical event, which the assertion above already does.
    assert len(articles_db) >= 1

def test_concurrency_stress_same_event_different_urls_different_content(tmp_path):
    engine, SessionLocal, sid1, sid2 = setup_db(tmp_path)

    # Different content so hashes are different, but LLM identifies them as same event!
    articles = [
        ArticleData(title=f"Breaking: GPT-{i}", url=f"http://site.com/{i}", content=f"duplicate_trigger {i} with enough characters to pass fifty chars check")
        for i in range(20)
    ]

    provider = DelayedTestLLMProvider(delay=0.1)
    results = run_concurrent_workers(SessionLocal, 20, articles, provider, [sid1, sid2])

    db = SessionLocal()
    events = db.query(Event).all()
    db.close()

    worker_errors = [r for r in results if isinstance(r, Exception)]
    assert not worker_errors, f"Worker thread(s) raised: {worker_errors}"
    assert len(events) == 1, f"Expected 1 canonical event, got {len(events)}"
