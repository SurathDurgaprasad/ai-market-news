import os
os.environ["TESTING"] = "1"

"""
Regressions for the production-hardening pass:

- an originating publisher behind an aggregator is not an "official" source
  unless its host is a registered primary source
- Python-side feed filters run before pagination, not after
- an unknown player slug is a 404, not an empty page
- a merged duplicate's detail points at the live canonical event
- related developments share an organization or a named entity, not a word
- the overview reports ingestion freshness from pipeline state
- consolidation compares only recent events
- market categories and attribution follow the event's subject
"""
import datetime
import uuid
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.consolidate import consolidate_safe_duplicates
from app.core.market import MarketEvent, _display_organization, build_market_overview, market_category
from app.db.base_class import Base
from app.db.session import get_db
from app.main import app
from app.models.event import Event
from app.models.source import Source

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine, expire_on_commit=False)


def _override_get_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override_get_db
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    try:
        yield TestClient(app)
    finally:
        Base.metadata.drop_all(bind=_engine)
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


def _now():
    return datetime.datetime.now(timezone.utc)


def _source(db, name, url, tier="primary"):
    source = Source(id=uuid.uuid4(), name=name, url=url, type="rss", tier=tier)
    db.add(source)
    db.commit()
    return source


def _event(db, source, **kwargs):
    values = dict(
        id=uuid.uuid4(),
        headline="Lab releases a model",
        short_summary="A lab released a model.",
        importance_score=70,
        citations=[],
        entities=[],
        primary_source_id=source.id,
        article_url="https://example.com/a",
        version=1,
        event_time=_now() - timedelta(minutes=5),
    )
    values.update(kwargs)
    event = Event(**values)
    db.add(event)
    db.commit()
    return event


# ── Provenance ───────────────────────────────────────────────────────────────

def test_origin_behind_aggregator_is_not_labeled_official(client):
    db = _Session()
    hn = _source(db, "Hacker News", "https://news.ycombinator.com/rss", tier="community")
    event = _event(
        db, hn,
        headline="US criticizes proposed algorithm opt-out laws",
        article_url="https://www.bbc.com/news/articles/abc",
        official_source_name="BBC News",
    )
    event_id = str(event.id)
    db.close()

    detail = client.get(f"/api/v1/events/{event_id}").json()
    assert detail["official_source"]["name"] == "BBC News"
    assert detail["official_source"]["tier"] == "origin"
    assert detail["ingest_source"]["tier"] == "community"


def test_origin_on_a_registered_primary_host_is_official(client):
    db = _Session()
    _source(db, "Anthropic News", "https://www.anthropic.com/news/rss", tier="primary")
    hn = _source(db, "Hacker News", "https://news.ycombinator.com/rss", tier="community")
    event = _event(
        db, hn,
        headline="Introduction of Claude Opus 5.5",
        article_url="https://www.anthropic.com/claude-opus-5-5",
        official_source_name="Anthropic",
    )
    event_id = str(event.id)
    db.close()

    detail = client.get(f"/api/v1/events/{event_id}").json()
    assert detail["official_source"]["tier"] == "primary"
    listed = client.get("/api/v1/events/").json()[0]
    assert listed["official_source"]["tier"] == "primary"


# ── Pagination with Python-side filters ─────────────────────────────────────

def test_week_scope_filters_before_pagination(client):
    db = _Session()
    news = _source(db, "Outlet", "https://outlet.example.com/feed", tier="secondary")
    base = _now() - timedelta(minutes=1)
    # 250 newer off-topic items would fill a naive SQL page entirely.
    for index in range(250):
        _event(db, news, headline=f"City council approves bakery permit {index}",
               short_summary="Local bakery news.", event_time=base - timedelta(seconds=index))
    for index in range(3):
        _event(db, news, headline=f"Lab releases open-weight model {index}",
               short_summary="A new language model.", event_time=base - timedelta(hours=1, seconds=index))
    db.close()

    week = client.get("/api/v1/events/?scope=week&limit=2").json()
    assert [item["headline"] for item in week] == [
        "Lab releases open-weight model 0",
        "Lab releases open-weight model 1",
    ]
    second = client.get("/api/v1/events/?scope=week&limit=2&skip=2").json()
    assert [item["headline"] for item in second] == ["Lab releases open-weight model 2"]


def test_player_filter_finds_matches_beyond_the_first_candidates(client):
    db = _Session()
    news = _source(db, "Outlet", "https://outlet.example.com/feed", tier="secondary")
    base = _now() - timedelta(minutes=1)
    for index in range(30):
        _event(db, news, headline=f"Startup ships model update {index}", entities=["Startup"],
               event_time=base - timedelta(seconds=index))
    _event(db, news, headline="Anthropic releases Claude model", entities=["Anthropic"],
           event_time=base - timedelta(hours=2))
    db.close()

    rows = client.get("/api/v1/events/?scope=week&limit=5&player=anthropic").json()
    assert [item["headline"] for item in rows] == ["Anthropic releases Claude model"]


def test_unknown_player_is_not_found(client):
    response = client.get("/api/v1/events/?scope=week&player=not-a-player")
    assert response.status_code == 404


# ── Canonical redirect and related developments ─────────────────────────────

def test_superseded_detail_points_to_live_canonical_through_a_chain(client):
    db = _Session()
    source = _source(db, "Lab Blog", "https://lab.example.com/feed")
    canonical = _event(db, source, headline="Lab introduces Model 5")
    middle = _event(db, source, headline="Model 5 introduced", superseded_by_id=canonical.id)
    oldest = _event(db, source, headline="Model 5 is here", superseded_by_id=middle.id)
    canonical_id, oldest_id = str(canonical.id), str(oldest.id)
    db.close()

    old = client.get(f"/api/v1/events/{oldest_id}").json()
    assert old["canonical_id"] == canonical_id
    assert old["superseded_by_id"] is not None
    live = client.get(f"/api/v1/events/{canonical_id}").json()
    assert live["canonical_id"] == canonical_id
    assert live["superseded_by_id"] is None


def test_related_developments_share_an_organization_not_a_word(client):
    db = _Session()
    blog = _source(db, "OpenAI Blog", "https://openai.com/news/rss.xml")
    news = _source(db, "Outlet", "https://outlet.example.com/feed", tier="secondary")
    base = _event(db, blog, headline="OpenAI introduces GPT-6", entities=["OpenAI", "GPT-6"],
                  importance_score=85)
    _event(db, news, headline="OpenAI publishes safety framework", entities=["OpenAI"],
           event_time=_now() - timedelta(hours=3))
    _event(db, news, headline="Unrelated lab introduces a model", entities=["Northwind"],
           event_time=_now() - timedelta(hours=1))
    _event(db, news, headline="OpenAI note from last month", entities=["OpenAI"],
           event_time=_now() - timedelta(days=30))
    base_id = str(base.id)
    db.close()

    related = client.get(f"/api/v1/events/{base_id}").json()["related"]
    assert [item["headline"] for item in related] == ["OpenAI publishes safety framework"]
    assert related[0]["reason"] == "OpenAI"


def test_overview_reports_ingestion_freshness(client):
    db = _Session()
    source = _source(db, "Lab Blog", "https://lab.example.com/feed")
    source.health_status = "failing"
    db.commit()
    _event(db, source)
    db.close()

    ingestion = client.get("/api/v1/events/overview").json()["ingestion"]
    assert ingestion["sources_enabled"] == 1
    assert ingestion["sources_failing"] == 1
    assert ingestion["last_ingested_at"]
    assert ingestion["llm_available"] is True


# ── Consolidation window ─────────────────────────────────────────────────────

def test_consolidation_ignores_events_outside_the_recent_window(db_session):
    source = db_session.query(Source).first()
    old = _now() - timedelta(days=60)
    for offset in (0, 10):
        db_session.add(Event(
            id=uuid.uuid4(),
            headline="Introduction of Claude Opus 5.5 Model",
            short_summary="Anthropic introduced Claude Opus 5.5.",
            importance_score=80,
            primary_source_id=source.id,
            article_url=f"https://example.com/{offset}",
            event_time=old + timedelta(minutes=offset),
            version=1,
        ))
    db_session.commit()
    assert consolidate_safe_duplicates(db_session) == 0
    # The same pair inside the window is still one development.
    assert consolidate_safe_duplicates(db_session, now=old + timedelta(days=1)) == 1


# ── Market categories and attribution ───────────────────────────────────────

def _market(headline, *, kind="other", summary="", tier="secondary", entities=None, org="", source="Outlet"):
    return MarketEvent(
        id=str(uuid.uuid4()),
        headline=headline,
        summary=summary or headline,
        importance=70,
        occurred_at=_now(),
        entities=entities or [],
        event_kind=kind,
        source_names=[source],
        source_tiers=[tier],
        organization_name=org,
        primary_source_name=source,
        primary_source_tier=tier,
    )


def test_security_kind_without_security_language_is_not_security():
    event = _market(
        "22 Nations Call for Global AI Oversight Body",
        kind="security_incident",
        summary="Twenty-two nations called for a global body to oversee AI.",
    )
    assert market_category(event) == "Policy"


def test_security_kind_with_security_language_stays_security():
    event = _market(
        "Microsoft disrupts AI-driven scam platform",
        kind="security_incident",
        summary="The platform was used to compromise accounts.",
    )
    assert market_category(event) == "Security"


def test_a_specific_kind_still_wins_over_policy_words():
    event = _market("Lab releases a model under new EU law", kind="model_release")
    assert market_category(event) == "Models"


def test_customer_story_on_a_vendor_platform_is_not_substantive():
    story = _market(
        "Reactiv Automates Mobile App Updates for Shopify Merchants Using Amazon Bedrock AgentCore",
        kind="capability",
        tier="primary",
        org="AWS AI",
        source="AWS Machine Learning Blog",
    )
    release = _market(
        "GPT-6 Sol and Luna Models Now Available on Amazon Bedrock",
        kind="model_release",
        tier="primary",
        org="AWS AI",
        source="AWS Machine Learning Blog",
    )
    overview = build_market_overview([story, release])
    amazon = next(item for item in overview["players"] if item["slug"] == "amazon")
    assert amazon["week"] == 2
    assert amazon["substantive"] == 1


def test_news_outlet_is_not_shown_as_the_subject_organization():
    event = _market("Startup raises $350 million", kind="funding", org="TechCrunch", source="TechCrunch AI")
    assert _display_organization(event) == ""
    official = _market("Lab ships a tokenizer", kind="tool_update", tier="primary", org="Hugging Face",
                       source="Hugging Face Blog")
    assert _display_organization(official) == "Hugging Face"


def test_pending_articles_are_counted_but_never_shown_as_events(client):
    from app.models.article import Article

    db = _Session()
    source = _source(db, "Lab Blog", "https://lab.example.com/feed")
    db.add(Article(
        id=uuid.uuid4(),
        source_id=source.id,
        url="https://lab.example.com/post",
        title="Lab ships a model",
        raw_content="Body text of the stored article.",
        hash="pending-hash",
        enrichment_status="pending",
        enrichment_error="LLM unavailable",
    ))
    db.commit()
    db.close()

    overview = client.get("/api/v1/events/overview").json()
    assert overview["ingestion"]["pending_enrichment"] == 1
    assert overview["ingestion"]["enrichment_paused"] is False
    assert client.get("/api/v1/events/?scope=week").json() == []


def test_resolve_reports_missing_and_canonical_events(client):
    db = _Session()
    source = _source(db, "Lab Blog", "https://lab.example.com/feed")
    canonical = _event(db, source, headline="Lab introduces Model 5")
    merged = _event(db, source, headline="Model 5 introduced", superseded_by_id=canonical.id)
    canonical_id, merged_id = str(canonical.id), str(merged.id)
    db.close()

    assert client.get(f"/api/v1/events/{canonical_id}/resolve").json()["canonical_id"] == canonical_id
    assert client.get(f"/api/v1/events/{merged_id}/resolve").json()["canonical_id"] == canonical_id
    assert client.get(f"/api/v1/events/{uuid.uuid4()}/resolve").status_code == 404
    assert client.get("/api/v1/events/not-a-uuid/resolve").status_code == 404
