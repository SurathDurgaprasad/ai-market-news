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


class MuseProvider(CountingProvider):
    def classify_event(self, content):
        return EventClassification(
            importance_score=70, importance_reasoning="device", entities=["Meta", "Muse Charm"],
            primary_entities=["Meta", "Muse Charm"], event_kind="hardware_platform",
            technical_change_scope="product", security_impact="none", tags=[], categories=["Hardware"],
        )


def test_a_product_named_inside_a_longer_entity_reaches_the_relationship_check(db_session):
    """Live: "Muse Charm" never matched a card whose only entity was "Muse", so two cards."""
    source = db_session.query(Source).first()
    match = "Tiny Hardware Device Provides New Mobile Home for AI Agent Muse"
    db_session.add(Event(
        id=uuid.uuid4(), headline=match, short_summary="A tiny wearable houses the agent.",
        entities=["Muse"], primary_source_id=source.id, version=1,
        importance_reasoning={"event_kind": "hardware_platform"},
    ))
    db_session.commit()
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = MuseProvider(match)
    event = pipeline.process_article(
        ArticleData(
            title="Meta's Muse AI Charms can interact with each other",
            url="https://news.example.com/muse-charm",
            content="Meta's Muse Charm is a handheld device with a 5G modem and a small touchscreen. " * 3,
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    assert pipeline.last_outcome == "linked"
    assert event is not None and event.headline == match


def test_recheck_merges_only_what_the_relationship_model_calls_the_same(db_session):
    from datetime import timedelta

    from app.core.consolidate import recheck_recent_duplicates
    from app.models.article import Article
    from app.models.event import EventArticle

    source = db_session.query(Source).first()
    now = datetime.now(timezone.utc)

    def card(headline, entities, text, hours_ago, kind="hardware_platform"):
        event = Event(id=uuid.uuid4(), headline=headline, short_summary=headline, entities=entities,
                      primary_source_id=source.id, version=1, event_time=now - timedelta(hours=hours_ago),
                      importance_reasoning={"event_kind": kind})
        article = Article(id=uuid.uuid4(), source_id=source.id, url=f"https://x.example/{uuid.uuid4()}",
                          title=headline, raw_content=text)
        db_session.add_all([event, article])
        db_session.flush()
        db_session.add(EventArticle(event_id=event.id, article_id=article.id, link_type="primary"))
        return event

    older = card("Tiny device houses agent Muse", ["Muse"], "A tiny wearable houses Muse.", 14)
    newer = card("Meta's Muse Charm interacts duplicate_trigger", ["Meta", "Muse Charm"], "Muse Charm.", 1)
    related = card("Meta ships Muse Charm SDK related_trigger", ["Muse Charm"], "An SDK.", 0.5)
    far = card("Muse Charm teardown duplicate_trigger", ["Muse Charm"], "Teardown.", 100)
    db_session.commit()

    llm = TestLLMProvider()
    assert recheck_recent_duplicates(db_session, llm) != []  # dry run reports
    db_session.expire_all()
    assert db_session.get(Event, older.id).superseded_by_id is None  # nothing changed

    merged = recheck_recent_duplicates(db_session, llm, apply=True)
    db_session.expire_all()
    assert len(merged) == 1
    survivors = {e.id for e in db_session.query(Event).filter(Event.superseded_by_id.is_(None))}
    assert len({older.id, newer.id} & survivors) == 1
    assert related.id in survivors and far.id in survivors


def test_canonical_card_is_the_one_that_says_who_acted():
    from app.core.consolidate import _prefer

    now = datetime.now(timezone.utc)
    vague = Event(headline="Tiny Hardware Device Provides New Mobile Home for AI Agent Muse",
                  entities=["Muse"], event_time=now.replace(hour=0), importance_score=70)
    named = Event(headline="Meta Announces Muse Charm Handheld AI Device",
                  entities=["Meta", "Muse Charm"], event_time=now.replace(hour=13), importance_score=70)
    assert min((vague, named), key=_prefer) is named
