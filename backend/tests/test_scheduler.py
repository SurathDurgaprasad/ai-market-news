"""
Source-aware scheduler: due-date selection, backoff, RSS type matching,
and skip-not-due behavior.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.core.scheduler import (
    IngestionScheduler,
    is_source_due,
    polling_interval_minutes,
    is_rss_source,
    POLLING_INTERVAL_MINUTES,
)
from app.models.source import Source
from app.core.providers.llm import TestLLMProvider


def _src(**kwargs) -> Source:
    defaults = dict(
        name="S",
        url="https://example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="medium",
        health_status="healthy",
        consecutive_failures=0,
    )
    defaults.update(kwargs)
    return Source(**defaults)


def test_polling_intervals_by_tier():
    assert polling_interval_minutes(_src(polling_tier="high")) == POLLING_INTERVAL_MINUTES["high"]
    assert polling_interval_minutes(_src(polling_tier="medium")) == POLLING_INTERVAL_MINUTES["medium"]
    assert polling_interval_minutes(_src(polling_tier="low")) == POLLING_INTERVAL_MINUTES["low"]
    assert polling_interval_minutes(_src(polling_tier="unknown")) == 20


def test_backoff_increases_interval_on_failure():
    src = _src(health_status="failing", consecutive_failures=2, polling_tier="medium")
    # 20 * 2^2 = 80
    assert polling_interval_minutes(src) == 80


def test_never_fetched_source_is_due():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    assert is_source_due(_src(last_fetch_at=None), now) is True


def test_recently_fetched_medium_source_is_not_due():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    src = _src(last_fetch_at=now - timedelta(minutes=5), polling_tier="medium")
    assert is_source_due(src, now) is False


def test_stale_medium_source_is_due():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    src = _src(last_fetch_at=now - timedelta(minutes=21), polling_tier="medium")
    assert is_source_due(src, now) is True


def test_high_tier_due_sooner_than_low():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
    high = _src(polling_tier="high", last_fetch_at=now - timedelta(minutes=11))
    low = _src(polling_tier="low", last_fetch_at=now - timedelta(minutes=11))
    assert is_source_due(high, now) is True
    assert is_source_due(low, now) is False


def test_rss_type_is_case_insensitive():
    assert is_rss_source("rss") is True
    assert is_rss_source("RSS") is True
    assert is_rss_source("Rss") is True
    assert is_rss_source("github") is False


def test_scheduler_skips_sources_that_are_not_due(db_session):
    now = datetime.now(timezone.utc)
    fresh = Source(
        name="Fresh",
        url="https://fresh.example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="medium",
        health_status="healthy",
        last_fetch_at=now,
    )
    stale = Source(
        name="Stale",
        url="https://stale.example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="medium",
        health_status="healthy",
        last_fetch_at=now - timedelta(hours=2),
    )
    db_session.add_all([fresh, stale])
    db_session.commit()

    fetched_urls = []
    db_session.close = MagicMock()
    scheduler = IngestionScheduler()

    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            def side_effect(url):
                fetched_urls.append(url)
                resp = MagicMock()
                resp.text = "<rss><channel></channel></rss>"
                return resp
            mock_fetch.side_effect = side_effect
            with patch("app.core.parser.parse_rss_feed", return_value=[]):
                scheduler.run_ingestion_cycle(now=now)

    assert "https://stale.example.com/rss" in fetched_urls
    assert "https://fresh.example.com/rss" not in fetched_urls


def test_scheduler_records_consecutive_failures(db_session):
    source = Source(
        name="Bad",
        url="https://bad.example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="high",
        consecutive_failures=1,
    )
    db_session.add(source)
    db_session.commit()
    db_session.close = MagicMock()
    scheduler = IngestionScheduler()

    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url", side_effect=Exception("timeout")):
            scheduler.run_ingestion_cycle()

    db_session.refresh(source)
    assert source.health_status == "failing"
    assert source.consecutive_failures == 2
    assert source.last_failure_at is not None


def test_scheduler_failure_isolation(db_session):
    source_good = Source(name="Good Source", url="https://good.com/rss", enabled=True, type="rss")
    source_bad = Source(name="Bad Source", url="https://bad.com/rss", enabled=True, type="RSS")
    db_session.add_all([source_good, source_bad])
    db_session.commit()

    scheduler = IngestionScheduler()
    db_session.close = MagicMock()

    with patch("app.core.scheduler.SessionLocal") as MockSessionLocal:
        MockSessionLocal.return_value = db_session
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            def side_effect(url):
                if "bad" in url:
                    raise Exception("Simulated connection timeout")
                mock_response = MagicMock()
                mock_response.text = "<rss></rss>"
                return mock_response
            mock_fetch.side_effect = side_effect
            with patch("app.core.parser.parse_rss_feed") as mock_parse:
                mock_parse.return_value = []
                scheduler.run_ingestion_cycle()

    db_session.refresh(source_good)
    db_session.refresh(source_bad)

    assert source_good.health_status == "healthy"
    assert source_good.last_error_info is None
    assert (source_good.consecutive_failures or 0) == 0

    assert source_bad.health_status == "failing"
    assert "Simulated connection timeout" in source_bad.last_error_info
    assert source_bad.last_failure_at is not None
    assert source_bad.consecutive_failures >= 1


def test_scheduler_recovers_after_success(db_session):
    source = Source(
        name="Recovering",
        url="https://recover.example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="high",
        health_status="failing",
        consecutive_failures=3,
    )
    db_session.add(source)
    db_session.commit()
    db_session.close = MagicMock()
    scheduler = IngestionScheduler()

    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = "<rss><channel></channel></rss>"
            mock_fetch.return_value = resp
            with patch("app.core.parser.parse_rss_feed", return_value=[]):
                scheduler.run_ingestion_cycle()

    db_session.refresh(source)
    assert source.health_status == "healthy"
    assert source.consecutive_failures == 0
    assert source.last_error_info is None


def test_scheduler_blocks_production_path_without_api_key(db_session, monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", None)
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", None)
    monkeypatch.setattr("app.core.config.settings.ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    source = Source(name="Prod Source", url="https://prod.example.com/rss", enabled=True, type="rss")
    db_session.add(source)
    db_session.commit()
    db_session.close = MagicMock()

    fetched = []
    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url", side_effect=lambda url: fetched.append(url)):
            result = scheduler.run_ingestion_cycle()

    assert result["blocked"] == "llm_unavailable"
    assert fetched == []
    from app.models.event import Event
    assert db_session.query(Event).count() == 0


def test_scheduler_test_runtime_uses_test_llm_and_records_stats(db_session, monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    from app.core.parser import ArticleData
    from app.core.providers.llm import TestLLMProvider
    from app.models.event import Event

    source = Source(name="Test RSS", url="https://test.example.com/rss", enabled=True, type="rss")
    db_session.add(source)
    db_session.commit()
    source_id = source.id
    db_session.close = MagicMock()

    article = ArticleData(
        title="A long enough headline about an AI model",
        url="https://test.example.com/post-1",
        content="This article contains enough characters to pass the minimum length validation check used by the pipeline.",
    )

    captured = []

    from app.core.pipeline import IntelligencePipeline

    class Capture(IntelligencePipeline):
        def __init__(self, db, llm_env=None):
            super().__init__(db, llm_env=llm_env)
            captured.append(self)

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = "<rss></rss>"
            mock_fetch.return_value = resp
            with patch("app.core.parser.parse_rss_feed", return_value=[article]):
                with patch("app.core.pipeline.IntelligencePipeline", Capture):
                    scheduler.run_ingestion_cycle()

    assert captured
    assert isinstance(captured[0].llm, TestLLMProvider)
    db_session.expire_all()
    src = db_session.query(Source).filter(Source.id == source_id).first()
    assert src.last_ingest_summary is not None
    assert "discovered=1" in src.last_ingest_summary
    assert db_session.query(Event).count() == 1
    assert db_session.query(Event).first().headline == "Mock Headline for TestCorp"


def test_scheduler_production_runtime_selects_nvidia_provider(db_session, monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", "nvapi-not-used")
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", None)

    source = Source(name="Prod RSS", url="https://prod-llm.example.com/rss", enabled=True, type="rss")
    db_session.add(source)
    db_session.commit()
    db_session.close = MagicMock()

    captured = []
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.llm import NVIDIAProvider, TestLLMProvider

    class Capture(IntelligencePipeline):
        def __init__(self, db, llm_env=None):
            super().__init__(db, llm_env=llm_env)
            captured.append(self)

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = "<rss></rss>"
            mock_fetch.return_value = resp
            with patch("app.core.parser.parse_rss_feed", return_value=[]):
                with patch("app.core.pipeline.IntelligencePipeline", Capture):
                    scheduler.run_ingestion_cycle()

    assert captured
    assert isinstance(captured[0].llm, NVIDIAProvider)
    assert not isinstance(captured[0].llm, TestLLMProvider)


def test_scheduler_openai_runtime_selects_openai_provider(db_session, monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "openai")
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-not-used")
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", None)

    source = Source(name="Prod RSS OpenAI", url="https://prod-openai.example.com/rss", enabled=True, type="rss")
    db_session.add(source)
    db_session.commit()
    db_session.close = MagicMock()

    captured = []
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.llm import ProductionLLMProvider, TestLLMProvider

    class Capture(IntelligencePipeline):
        def __init__(self, db, llm_env=None):
            super().__init__(db, llm_env=llm_env)
            captured.append(self)

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = "<rss></rss>"
            mock_fetch.return_value = resp
            with patch("app.core.parser.parse_rss_feed", return_value=[]):
                with patch("app.core.pipeline.IntelligencePipeline", Capture):
                    scheduler.run_ingestion_cycle()

    assert captured
    assert isinstance(captured[0].llm, ProductionLLMProvider)
    assert not isinstance(captured[0].llm, TestLLMProvider)
