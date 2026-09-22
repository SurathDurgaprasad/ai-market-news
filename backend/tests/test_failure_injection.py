import pytest
from app.core.pipeline import IntelligencePipeline
from app.core.providers.llm import LLMProvider, LlmUnavailableError, EventClassification
from app.core.ai_processor import SourceGroundedSummary
from app.core.parser import ArticleData
from datetime import datetime, timezone
from uuid import uuid4


class FailingLLMProvider(LLMProvider):
    """Minimal LLMProvider double for exercising pipeline failure paths."""

    def __init__(self, fail_on="timeout"):
        self.fail_on = fail_on
        self.calls = 0

    def classify_event(self, content: str):
        self.calls += 1
        if self.fail_on == "timeout":
            raise LlmUnavailableError("LLM API timed out")
        if self.fail_on == "unparseable":
            # Simulates the provider giving up on malformed model output
            # (see NVIDIAProvider.classify_event, which returns None rather
            # than raising when the schema can't be validated).
            return None
        return EventClassification(
            tags=["Test"],
            categories=["Test"],
            entities=["TestCorp"],
            primary_entities=["TestCorp"],
            mentioned_entities=[],
            event_kind="other",
            technical_change_scope="product",
            security_impact="none",
            importance_score=50,
            importance_reasoning="test",
        )

    def summarize_event(self, content: str):
        return SourceGroundedSummary(
            headline="Success",
            short_summary="Success summary",
            what_changed="",
            citations=[],
        )

    def is_same_event(self, content: str, event_summary: str, context=None) -> bool:
        return False


def _make_source(db_session, name="Test Source", url="http://test.com"):
    from app.models.source import Source
    source = Source(id=uuid4(), name=name, url=url)
    db_session.add(source)
    db_session.commit()
    return source


def test_pipeline_llm_timeout(db_session):
    """
    An LLM timeout/outage must propagate, not be swallowed into a silent
    reject. This is intentional fail-closed behavior (see pipeline.py's
    explicit `except LlmUnavailableError: ... raise`): the caller
    (app/core/scheduler.py::run_ingestion_cycle) depends on this exception
    reaching it so it can mark the whole ingestion cycle as LLM-blocked,
    rather than the pipeline silently treating every article as "rejected"
    and masking a full provider outage as ordinary noise filtering.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = FailingLLMProvider(fail_on="timeout")

    source = _make_source(db_session)
    article_data = ArticleData(
        title="Test Article",
        url="http://test.com/1",
        content="This is a test article. " * 10,
        published_at=datetime.now(timezone.utc)
    )

    with pytest.raises(LlmUnavailableError):
        pipeline.process_article(article_data, source.id)

    assert pipeline.last_outcome == "llm_unavailable"


def test_pipeline_classification_unparseable_is_rejected_cleanly(db_session):
    """
    When the provider cannot produce a usable classification at all (e.g.
    NVIDIA returned unparseable JSON across every JSON mode and
    NVIDIAProvider.classify_event returns None rather than raising), the
    pipeline must reject the article cleanly — no exception, no event
    created — rather than crashing on `classification.importance_score`.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = FailingLLMProvider(fail_on="unparseable")

    source = _make_source(db_session, name="Test Source 2", url="http://test2.com")
    article_data = ArticleData(
        title="Test Article",
        url="http://test.com/2",
        content="This is a test article. " * 10,
        published_at=datetime.now(timezone.utc)
    )

    event = pipeline.process_article(article_data, source.id)
    assert event is None
    assert pipeline.last_outcome == "rejected"
    assert pipeline.llm.calls == 1
