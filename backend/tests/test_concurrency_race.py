import threading
import time
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.models.article import Article
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.providers.llm import TestLLMProvider


def _file_backed_engine(tmp_path):
    """
    A real file-backed SQLite engine, matching production's pooling model
    (app/db/session.py only uses StaticPool for `:memory:`/`sqlite://` —
    everything else gets SQLAlchemy's normal per-connection pooling).

    Deliberately NOT `:memory:` + StaticPool: StaticPool hands every
    session the exact same raw sqlite3 connection/cursor object, and two
    real OS threads issuing statements on that one shared object
    concurrently corrupts its cursor state (observed as
    `sqlite3.InterfaceError: bad parameter or other API misuse` in an
    earlier version of this test) — a test-harness artifact that cannot
    happen in production, where each request gets its own pooled
    connection onto the same file. A temp file reproduces the real
    concurrency model (separate connections, SQLite's own file locking,
    WAL) instead of a fragile single-connection stand-in.
    """
    db_path = tmp_path / "concurrency_race.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return engine


def test_concurrent_same_event_different_urls(tmp_path):
    engine = _file_backed_engine(tmp_path)
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

    def worker_process(article_data, result_container, error_container, index):
        db = SessionLocal()
        try:
            pipeline = IntelligencePipeline(db, llm_env="test")
            pipeline.llm = DelayedTestLLMProvider()  # Override LLM to inject delay
            event = pipeline.process_article(article_data, source_id)
            if event:
                result_container[index] = event.id
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            error_container[index] = exc
        finally:
            db.close()

    results = [None, None]
    errors = [None, None]

    t1 = threading.Thread(target=worker_process, args=(article_a, results, errors, 0))
    t2 = threading.Thread(target=worker_process, args=(article_b, results, errors, 1))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # A crashed worker must fail the test loudly, not silently reduce the
    # event count and let the assertion below pass for the wrong reason.
    assert errors == [None, None], f"Worker thread(s) raised: {errors}"

    # Check the database for events
    db = SessionLocal()
    events = db.query(Event).all()
    db.close()

    # If the system is robust against concurrent insertion, there should be exactly ONE event.
    # If it's vulnerable to the race condition, there will be TWO events.
    assert len(events) == 1, f"Concurrency failure: {len(events)} duplicate canonical events were created!"
