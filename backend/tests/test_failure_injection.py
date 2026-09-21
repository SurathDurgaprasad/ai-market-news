import pytest
from app.core.pipeline import IntelligencePipeline
from app.models.article import Article
from app.core.parser import ArticleData
from datetime import datetime, timezone
from uuid import uuid4

class FailingLLMProvider:
    def __init__(self, fail_on="timeout"):
        self.fail_on = fail_on
        self.calls = 0

    def generate_extraction(self, article_data, existing_events):
        self.calls += 1
        from app.core.llm import LlmUnavailableError
        if self.fail_on == "timeout":
            raise LlmUnavailableError("LLM API timed out")
            
        from app.core.llm import EventExtraction
        if self.fail_on == "malformed":
            return None # Simulate JSON parse failure returning None
        elif self.fail_on == "missing_fields":
            return EventExtraction(headline="It happened", importance_score=50, short_summary="", what_changed="", citations=[]) # Missing short_summary
        elif self.fail_on == "drop":
            return None
        return EventExtraction(headline="Success", short_summary="Success summary", importance_score=50, what_changed="", citations=[])

    def classify_event(self, text: str):
        from app.core.providers.llm import LlmUnavailableError
        if self.fail_on == "timeout":
            raise LlmUnavailableError("LLM API timed out")
            
        from app.core.providers.llm import EventClassification
        return EventClassification(
            is_ai_event=True,
            importance_score=50,
            event_kind="other",
            technical_change_scope="product",
            security_impact="none",
            organizations=[],
            products=[],
            people=[]
        )

    def compare_events(self, new_text: str, existing_events: list):
        return None

def test_pipeline_llm_timeout(db_session):
    # If the LLM times out, the pipeline should catch the exception,
    # log it, and return None (dropping the article for now, maybe retry later).
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = FailingLLMProvider(fail_on="timeout")
    
    from app.models.source import Source
    source = Source(id=uuid4(), name="Test Source", url="http://test.com")
    db_session.add(source)
    db_session.commit()

    article_data = ArticleData(
        title="Test Article",
        url="http://test.com/1",
        content="This is a test article." * 10,
        published_at=datetime.now(timezone.utc)
    )

    # Pipeline should not crash
    event = pipeline.process_article(article_data, source.id)
    assert event is None
    assert pipeline.last_outcome == "llm_error"

def test_pipeline_llm_missing_fields(db_session):
    # If the LLM returns missing fields, the JSON parser should handle it
    # or the pipeline should reject the incomplete event.
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = FailingLLMProvider(fail_on="missing_fields")
    
    from app.models.source import Source
    source = Source(id=uuid4(), name="Test Source 2", url="http://test2.com")
    db_session.add(source)
    db_session.commit()

    article_data = ArticleData(
        title="Test Article",
        url="http://test.com/2",
        content="This is a test article." * 10,
        published_at=datetime.now(timezone.utc)
    )

    event = pipeline.process_article(article_data, source.id)
    # The pipeline rejects events that are missing short_summary or headline
    assert event is None
    assert pipeline.last_outcome == "llm_error" or pipeline.last_outcome == "dropped"

