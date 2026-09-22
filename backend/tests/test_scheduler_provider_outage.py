"""
Phase 1A: scheduler / ingestion architecture red team.

Invariant under test (from the operating brief): "A provider outage must
be distinguishable from 'no AI events found'."

Root cause traced: app/core/pipeline.py only catches LlmUnavailableError
around the classify_event call:

    try:
        classification = self.llm.classify_event(content)
    except LlmUnavailableError:
        self.last_outcome = "llm_unavailable"
        raise

But NVIDIAProvider.classify_event only raises LlmUnavailableError when
`self.client` is None (no API key configured). A genuine network/API
outage — the tenacity-wrapped retry exhausting all attempts on a
ProviderRequestTimeout, a connection error, or a persistent rate limit —
propagates out of classify_event as THAT exception, not
LlmUnavailableError. pipeline.py doesn't catch it, so it propagates to
scheduler.py's per-article loop, which DOES have a broad
`except Exception as art_err` fallback — it logs, increments `rejected`,
and (critically) does NOT set llm_blocked and does NOT break the article
loop. Every remaining article in that source's feed then repeats the
same failed call. At the end, `llm_blocked` is still False, so the
source is recorded `health_status="healthy"` with `last_fetch_at`
updated — identical to a source that was successfully polled and simply
had zero newsworthy articles that cycle.
"""
from unittest.mock import patch, MagicMock

from app.core.scheduler import IngestionScheduler
from app.core.providers.llm import LLMProvider, LlmUnavailableError
from app.models.source import Source


class _OutageLLMProvider(LLMProvider):
    """Simulates a persistent provider outage: every call raises a raw
    transport-level exception, never LlmUnavailableError directly —
    exactly what NVIDIAProvider does today once tenacity's retries are
    exhausted on a real network/timeout failure."""

    def __init__(self):
        self.calls = 0

    def classify_event(self, content: str):
        self.calls += 1
        raise TimeoutError("simulated persistent NVIDIA outage")

    def summarize_event(self, content: str):
        raise TimeoutError("simulated persistent NVIDIA outage")

    def is_same_event(self, content: str, event_summary: str, context=None) -> bool:
        raise TimeoutError("simulated persistent NVIDIA outage")


def _run_cycle_with_outage_provider(db_session, articles):
    from app.core.parser import ArticleData
    from app.core.pipeline import IntelligencePipeline

    source = Source(name="Outage Source", url="https://outage.example.com/rss", enabled=True, type="rss")
    db_session.add(source)
    db_session.commit()
    source_id = source.id
    db_session.close = MagicMock()

    captured = []

    class Capture(IntelligencePipeline):
        def __init__(self, db, llm_env=None):
            super().__init__(db, llm_env="test")
            self.llm = _OutageLLMProvider()
            captured.append(self)

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = "<rss></rss>"
            mock_fetch.return_value = resp
            with patch("app.core.parser.parse_rss_feed", return_value=articles):
                with patch("app.core.pipeline.IntelligencePipeline", Capture):
                    scheduler.run_ingestion_cycle()

    db_session.expire_all()
    src = db_session.query(Source).filter(Source.id == source_id).first()
    return src, captured


def test_provider_outage_is_recorded_as_degraded_not_healthy(db_session):
    """
    THE regression test for this finding. A source whose every article
    fails classification due to a provider-level outage must NOT be
    recorded as health_status="healthy" — that is indistinguishable from
    "the source had nothing newsworthy this cycle" and silently hides a
    total ingestion outage from the admin sources page.
    """
    from app.core.parser import ArticleData

    articles = [
        ArticleData(
            title=f"Article {i}",
            url=f"https://outage.example.com/post-{i}",
            content="This article has enough characters to pass the minimum length validation check in the pipeline.",
        )
        for i in range(3)
    ]

    src, captured = _run_cycle_with_outage_provider(db_session, articles)

    assert captured and captured[0].llm.calls >= 1, "outage provider was never actually invoked"
    assert src.health_status != "healthy", (
        "A source where the LLM provider failed on every single article was recorded "
        "healthy — a genuine outage is indistinguishable from a quiet news day."
    )
    assert src.last_error_info, "An outage must leave a diagnosable error message, not a silent 'healthy'."


def test_provider_outage_does_not_retry_every_remaining_article(db_session):
    """
    Neighboring invariant: 'retry storms must not occur' and 'a slow
    article must not indefinitely block a cycle'. Once the provider is
    confirmed down for this source, the cycle should stop hammering it
    with the REST of that source's articles — not attempt all N and fail
    N times individually.
    """
    from app.core.parser import ArticleData

    articles = [
        ArticleData(
            title=f"Article {i}",
            url=f"https://outage.example.com/post-{i}",
            content="This article has enough characters to pass the minimum length validation check in the pipeline.",
        )
        for i in range(10)
    ]

    src, captured = _run_cycle_with_outage_provider(db_session, articles)

    assert captured[0].llm.calls < 10, (
        f"Provider was called {captured[0].llm.calls} times for 10 articles from an already-confirmed-down "
        f"source — outage detection should stop processing the rest of this source's articles, not retry each one."
    )
