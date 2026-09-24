"""
An article sharing one common entity with many recent events is compared by
the LLM only against the most similar few, and the true match is among them.
Live: one article cost 22 sequential ~30s relationship calls.
"""
import uuid
from datetime import datetime, timezone

from app.core.ai_processor import EventClassification
from app.core.parser import ArticleData
from app.core.pipeline import MAX_RELATIONSHIP_CHECKS, IntelligencePipeline
from app.core.providers.llm import EventRelationship, RelationshipResult, TestLLMProvider
from app.models.event import Event
from app.models.source import Source


class CountingProvider(TestLLMProvider):
    def __init__(self, match_headline):
        super().__init__()
        self.match_headline = match_headline
        self.relationship_calls = 0

    def classify_event(self, content):
        return EventClassification(
            importance_score=70,
            importance_reasoning="security incident",
            entities=["OpenAI", "Medicare"],
            primary_entities=["OpenAI", "Medicare"],
            event_kind="security_incident",
            technical_change_scope="product",
            security_impact="significant",
            tags=["security"],
            categories=["Security"],
        )

    def classify_relationship(self, content, event_summary, context=None):
        self.relationship_calls += 1
        same = event_summary.startswith(self.match_headline)
        return RelationshipResult(
            relationship=EventRelationship.SAME_EVENT if same else EventRelationship.DIFFERENT_EVENT,
            reasoning="test",
        )


def test_true_match_is_found_within_the_relationship_budget(db_session):
    source = db_session.query(Source).first()
    match = "Australian Medicare system hacked by OpenAI agents"
    # The true match is the OLDEST candidate; 12 newer events share only "OpenAI".
    db_session.add(Event(
        id=uuid.uuid4(), headline=match, short_summary="Agents breached Medicare health data systems.",
        entities=["OpenAI", "Medicare"], primary_source_id=source.id, version=1,
        importance_reasoning={"event_kind": "security_incident"},
    ))
    db_session.commit()
    for index in range(12):
        db_session.add(Event(
            id=uuid.uuid4(), headline=f"OpenAI ships product update {index}",
            short_summary="OpenAI released a product update for developers.",
            entities=["OpenAI"], primary_source_id=source.id, version=1,
            importance_reasoning={"event_kind": "security_incident"},
        ))
    db_session.commit()

    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = CountingProvider(match)
    event = pipeline.process_article(
        ArticleData(
            title="Australia to investigate OpenAI agents hack of Medicare health data",
            url="https://news.example.com/medicare-hack",
            content="Australia will investigate how OpenAI agents hacked Medicare health data systems. " * 3,
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    assert pipeline.last_outcome == "linked"
    assert event is not None and event.headline == match
    assert pipeline.llm.relationship_calls <= MAX_RELATIONSHIP_CHECKS
    assert pipeline.llm.relationship_calls == 1  # most similar candidate is asked first


def test_relationship_calls_never_exceed_the_budget(db_session):
    source = db_session.query(Source).first()
    for index in range(20):
        db_session.add(Event(
            id=uuid.uuid4(), headline=f"OpenAI ships product update {index}",
            short_summary="OpenAI released a product update.", entities=["OpenAI"],
            primary_source_id=source.id, version=1, importance_reasoning={"event_kind": "security_incident"},
        ))
    db_session.commit()
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = CountingProvider("no such event")
    pipeline.process_article(
        ArticleData(
            title="OpenAI discloses an unrelated incident",
            url="https://news.example.com/other",
            content="OpenAI disclosed an unrelated incident affecting Medicare integrations. " * 3,
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    assert pipeline.llm.relationship_calls == MAX_RELATIONSHIP_CHECKS
    assert pipeline.last_outcome == "created"
