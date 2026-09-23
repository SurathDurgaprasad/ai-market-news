import os
os.environ["TESTING"] = "1"

"""
Tests for the /api/v1/events/ endpoints.

Uses FastAPI TestClient with a real in-memory SQLite database (StaticPool ensures
all sessions share the same connection, which is required for SQLite :memory:).

Tests validate:
- response schema correctness
- pagination and ordering
- min_importance filtering
- exclusion of superseded events
- new_count semantics
- source attribution correctness (regression test for cross-join attribution bug)
- UUID validation
"""
import uuid
import datetime
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.session import get_db
from app.db.base_class import Base
from app.models.event import Event, EventArticle
from app.models.source import Source
from app.models.article import Article

# ── Shared in-memory SQLite with StaticPool ────────────────────────────────
# StaticPool reuses one underlying connection so all sessions share the same
# in-memory database. Without it, different connections each get an empty DB.

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=_engine,
    expire_on_commit=False,  # prevent DetachedInstanceError after session.close()
)


def override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_tables():
    """Recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(bind=_engine)
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_source(db, name="Test Source", url="https://test-source.example.com") -> Source:
    source = Source(
        id=uuid.uuid4(),
        name=name,
        url=url,
        type="rss",
        tier="primary",
    )
    db.add(source)
    db.commit()
    return source


def _make_event(db, source: Source, **kwargs) -> Event:
    defaults = dict(
        id=uuid.uuid4(),
        headline="Test Event Headline",
        short_summary="A short factual summary.",
        what_changed="Something technical changed.",
        importance_score=70,
        citations=[],
        entities=["TestCorp", "Model X"],
        primary_source_id=source.id,
        article_url="https://example.com/article",
        version=1,
    )
    defaults.update(kwargs)
    event = Event(**defaults)
    db.add(event)
    db.commit()
    return event


def _iso(dt: datetime.datetime) -> str:
    """URL-encode a datetime ISO string (handles the + in timezone offsets)."""
    return quote(dt.isoformat())


# ── Health check ─────────────────────────────────────────────────────────────

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "AI World Intelligence Platform" in body["service"]
    assert body["llm_mode"] == "test"
    assert body["llm_provider"] == "test"
    assert body["test_runtime"] is True
    assert body["scheduler_enabled"] is False


# ── GET /api/v1/events/ ───────────────────────────────────────────────────────

def test_events_returns_empty_list_when_no_events():
    response = client.get("/api/v1/events/")
    assert response.status_code == 200
    assert response.json() == []


def test_events_returns_event_list():
    db = _TestingSessionLocal()
    source = _make_source(db)
    _make_event(db, source, headline="GPT-5 Released", importance_score=90)
    _make_event(db, source, headline="Claude 4 Released", importance_score=80)
    db.close()

    response = client.get("/api/v1/events/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2


def test_events_response_schema_contains_required_fields():
    """Every event in the list response must include required fields and NOT include removed fields."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    event = _make_event(
        db, source,
        headline="Claude 4 announced",
        short_summary="Anthropic released Claude 4.",
        importance_score=85,
        entities=["Anthropic", "Claude 4"],
        article_url="https://anthropic.com/claude-4",
    )
    db.close()

    response = client.get("/api/v1/events/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    item = body[0]

    assert item["id"] == str(event.id)
    assert item["headline"] == "Claude 4 announced"
    assert item["short_summary"] == "Anthropic released Claude 4."
    assert item["importance_score"] == 85
    assert "created_at" in item
    assert "entities" in item
    assert "Anthropic" in item["entities"]
    # why_it_matters must NOT appear in the response (removed per PRD — no editorial commentary)
    assert "why_it_matters" not in item
    assert item["image_role"] in ("hero", "source", "none")
    assert item["image_role"] in ("hero", "source", "none")


def test_events_ordered_by_created_at_when_event_time_missing():
    """When event_time is absent, ingestion time is the fallback sort key."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    now = datetime.datetime.now(datetime.timezone.utc)
    _make_event(db, source, headline="Older Event", importance_score=60,
                created_at=now - datetime.timedelta(hours=2))
    _make_event(db, source, headline="Newer Event", importance_score=60,
                created_at=now - datetime.timedelta(hours=1))
    db.close()

    response = client.get("/api/v1/events/")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["headline"] == "Newer Event"
    assert body[1]["headline"] == "Older Event"


def test_events_ordered_by_event_time_not_ingestion_time():
    """
    Feed order is real-world recency. A newly ingested older article must not
    appear above a more recent development just because created_at is newer.
    """
    db = _TestingSessionLocal()
    source = _make_source(db)
    now = datetime.datetime.now(datetime.timezone.utc)
    _make_event(
        db, source,
        headline="Old world, ingested now",
        importance_score=60,
        event_time=now - datetime.timedelta(days=40),
        created_at=now,
    )
    _make_event(
        db, source,
        headline="Recent world, ingested earlier",
        importance_score=60,
        event_time=now - datetime.timedelta(hours=6),
        created_at=now - datetime.timedelta(days=1),
    )
    db.close()

    body = client.get("/api/v1/events/").json()
    assert [item["headline"] for item in body] == [
        "Recent world, ingested earlier",
        "Old world, ingested now",
    ]


def test_events_list_excludes_empty_summaries():
    """High-signal feed must not present failed extractions as finished intelligence."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    _make_event(db, source, headline="Incomplete", short_summary="   ")
    complete = _make_event(db, source, headline="Complete", short_summary="A grounded summary.")
    db.close()

    body = client.get("/api/v1/events/").json()
    assert [item["headline"] for item in body] == ["Complete"]
    assert body[0]["id"] == str(complete.id)


def test_events_list_excludes_missing_article_url():
    db = _TestingSessionLocal()
    source = _make_source(db)
    _make_event(db, source, headline="No URL", article_url="")
    complete = _make_event(db, source, headline="Has URL", article_url="https://vendor.example/post")
    db.close()

    body = client.get("/api/v1/events/").json()
    assert [item["headline"] for item in body] == ["Has URL"]


def test_event_detail_still_returns_incomplete_event():
    """Incomplete events stay addressable by ID even when excluded from the feed."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    event = _make_event(db, source, headline="Incomplete", short_summary="")
    event_id = str(event.id)
    db.close()

    listed = client.get("/api/v1/events/").json()
    assert listed == []

    response = client.get(f"/api/v1/events/{event_id}")
    assert response.status_code == 200
    assert response.json()["headline"] == "Incomplete"
    assert response.json()["short_summary"] == ""


def test_events_excludes_superseded_events():
    """Events with superseded_by_id set must NOT appear in the main feed."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    new_event = _make_event(db, source, headline="New Version", importance_score=70)
    old_event = _make_event(db, source, headline="Old Version", importance_score=70,
                            superseded_by_id=new_event.id)
    new_id = str(new_event.id)
    old_id = str(old_event.id)
    db.close()

    response = client.get("/api/v1/events/")
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()]
    assert new_id in ids
    assert old_id not in ids


def test_events_pagination():
    """skip/limit parameters must work correctly."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    for i in range(5):
        _make_event(db, source, headline=f"Event {i}", importance_score=50)
    db.close()

    r1 = client.get("/api/v1/events/?limit=2&skip=0")
    r2 = client.get("/api/v1/events/?limit=2&skip=2")
    r3 = client.get("/api/v1/events/?limit=2&skip=4")

    assert len(r1.json()) == 2
    assert len(r2.json()) == 2
    assert len(r3.json()) == 1


def test_events_min_importance_filter():
    """min_importance query param must filter events below threshold."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    _make_event(db, source, headline="High Impact", importance_score=80)
    _make_event(db, source, headline="Low Noise", importance_score=20)
    db.close()

    response = client.get("/api/v1/events/?min_importance=50")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["headline"] == "High Impact"


# ── GET /api/v1/events/{id} ───────────────────────────────────────────────────

def test_get_event_by_id_returns_correct_event():
    db = _TestingSessionLocal()
    source = _make_source(db)
    event = _make_event(db, source, headline="Specific Event", importance_score=75,
                        entities=["OpenAI", "GPT-5"])
    event_id = str(event.id)
    db.close()

    response = client.get(f"/api/v1/events/{event_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == event_id
    assert body["headline"] == "Specific Event"
    assert "OpenAI" in body["entities"]
    assert "why_it_matters" not in body


def test_get_event_by_id_returns_404_for_unknown():
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/events/{fake_id}")
    assert response.status_code == 404


def test_get_event_by_id_returns_400_for_invalid_uuid():
    """A malformed event ID should return 400, not 500."""
    response = client.get("/api/v1/events/not-a-real-uuid")
    assert response.status_code == 400


def test_get_event_source_attribution_is_correct():
    """
    Regression: the source returned with an event must correspond to the
    actual source the article was fetched from, not an arbitrary other source.
    This prevents the cross-join attribution bug.
    """
    db = _TestingSessionLocal()

    source_a = _make_source(db, name="Official OpenAI Blog", url="https://openai.com/blog")
    source_b = _make_source(db, name="TechCrunch", url="https://techcrunch.com")

    event_a = _make_event(db, source_a, headline="OpenAI Event",
                          importance_score=80, primary_source_id=source_a.id)
    event_b = _make_event(db, source_b, headline="TechCrunch Event",
                          importance_score=60, primary_source_id=source_b.id)
    id_a, id_b = str(event_a.id), str(event_b.id)
    db.close()

    resp_a = client.get(f"/api/v1/events/{id_a}")
    resp_b = client.get(f"/api/v1/events/{id_b}")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Each event must carry its own source attribution — not the other's
    assert resp_a.json()["primary_source"]["name"] == "Official OpenAI Blog"
    assert resp_b.json()["primary_source"]["name"] == "TechCrunch"


def test_api_prefers_official_publisher_for_aggregator_ingest():
    db = _TestingSessionLocal()
    hn = _make_source(db, name="Hacker News", url="https://news.ycombinator.com/rss")
    event = _make_event(
        db, hn,
        headline="Hacktron exploits libheif RCE",
        article_url="https://www.hacktron.ai/blog/hacking-openai",
        official_source_name="Hacktron",
    )
    event_id = str(event.id)
    db.close()

    detail = client.get(f"/api/v1/events/{event_id}").json()
    listed = client.get("/api/v1/events/").json()[0]
    assert detail["primary_source"]["name"] == "Hacktron"
    assert detail["ingest_source"]["name"] == "Hacker News"
    assert detail["official_source"]["name"] == "Hacktron"
    assert listed["primary_source"]["name"] == "Hacktron"
    assert listed["ingest_source"]["name"] == "Hacker News"


# ── GET /api/v1/events/new_count ─────────────────────────────────────────────

def test_new_count_returns_zero_when_no_new_events():
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc)
    _make_event(db, source, headline="Old Event", importance_score=60,
                created_at=reference_time - datetime.timedelta(hours=1))
    db.close()

    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 0


def test_new_count_returns_correct_count_of_new_events():
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)

    # One old event (must not be counted)
    _make_event(db, source, headline="Old Event", importance_score=60,
                created_at=reference_time - datetime.timedelta(hours=1))
    # Two new events (must be counted)
    _make_event(db, source, headline="New Event 1", importance_score=70,
                created_at=reference_time + datetime.timedelta(minutes=1))
    _make_event(db, source, headline="New Event 2", importance_score=70,
                created_at=reference_time + datetime.timedelta(minutes=2))
    db.close()

    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 2


def test_new_count_excludes_superseded_events():
    """Superseded events must not inflate the new count even if created after 'since'."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)

    new_event = _make_event(db, source, headline="New Version", importance_score=70,
                            created_at=reference_time + datetime.timedelta(minutes=1))
    # This superseded event was also created after reference_time — must be excluded
    _make_event(db, source, headline="Superseded Version", importance_score=70,
                created_at=reference_time + datetime.timedelta(minutes=1),
                superseded_by_id=new_event.id)
    db.close()

    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    # Only the active (non-superseded) event counts
    assert response.json()["new_events_count"] == 1


def test_new_count_excludes_incomplete_events():
    """Failed extractions must not inflate the new-events chip."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    _make_event(
        db, source,
        headline="Incomplete",
        short_summary="  ",
        created_at=reference_time + datetime.timedelta(minutes=1),
    )
    _make_event(
        db, source,
        headline="Complete",
        short_summary="A grounded summary.",
        created_at=reference_time + datetime.timedelta(minutes=2),
    )
    db.close()
    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 1


def test_new_count_requires_since_parameter():
    """The since parameter is required — missing it must return 422."""
    response = client.get("/api/v1/events/new_count")
    assert response.status_code == 422


def test_new_count_ignores_old_event_time_if_created_at_is_old():
    """
    An event whose real-world event_time is recent but created_at is old
    must NOT appear in new_count. new_count is ingestion-time, not event_time.
    """
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc)
    _make_event(
        db, source,
        headline="Backdated event_time",
        importance_score=70,
        created_at=reference_time - datetime.timedelta(hours=3),
        event_time=reference_time + datetime.timedelta(minutes=1),
    )
    db.close()
    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 0


def test_new_count_includes_old_article_newly_ingested():
    """Old publication, new ingestion → created_at is new → counts as a new event."""
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    old_pub = reference_time - datetime.timedelta(days=5)
    _make_event(
        db, source,
        headline="Old article newly discovered",
        importance_score=70,
        created_at=reference_time + datetime.timedelta(seconds=30),
        event_time=old_pub,
    )
    db.close()
    response = client.get(f"/api/v1/events/new_count?since={_iso(reference_time)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 1


def test_list_endpoint_exposes_event_time_separately_from_created_at():
    db = _TestingSessionLocal()
    source = _make_source(db)
    pub = datetime.datetime(2026, 1, 1, 8, 0, tzinfo=datetime.timezone.utc)
    created = datetime.datetime(2026, 9, 18, 10, 0, tzinfo=datetime.timezone.utc)
    _make_event(
        db, source,
        headline="Timestamp split",
        importance_score=70,
        created_at=created,
        event_time=pub,
    )
    db.close()
    body = client.get("/api/v1/events/").json()
    assert len(body) == 1
    assert body[0]["event_time"].startswith("2026-01-01")
    assert body[0]["created_at"].startswith("2026-09-18")
    assert body[0]["event_time"].endswith("+00:00") or body[0]["event_time"].endswith("Z")
    assert body[0]["created_at"].endswith("+00:00") or body[0]["created_at"].endswith("Z")


def test_new_count_does_not_increment_for_supporting_articles_on_existing_event():
    """
    Five new source articles attached to ONE canonical event must not make
    new_count == 5. new_count is canonical-event creation, not article count.

    Product decision: a material same-URL content update creates a new
    versioned Event (superseding the old row) and DOES count as new.
    Additional supporting coverage does not.
    """
    db = _TestingSessionLocal()
    source = _make_source(db)
    reference_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    event = _make_event(
        db, source,
        headline="Canonical event",
        importance_score=80,
        created_at=reference_time,
    )
    for i in range(5):
        article = Article(
            id=uuid.uuid4(),
            source_id=source.id,
            url=f"https://outlet-{i}.example.com/story",
            title=f"Coverage {i}",
            raw_content="enough",
            hash=f"hash-{i}",
        )
        db.add(article)
        db.flush()
        db.add(EventArticle(event_id=event.id, article_id=article.id, link_type="supporting"))
    db.commit()
    db.close()

    since = reference_time + datetime.timedelta(minutes=1)
    response = client.get(f"/api/v1/events/new_count?since={_iso(since)}")
    assert response.status_code == 200
    assert response.json()["new_events_count"] == 0


def test_api_strips_wrapping_citation_quotes():
    db = _TestingSessionLocal()
    source = _make_source(db)
    event = _make_event(
        db, source,
        headline="Quoted evidence",
        citations=[
            '"The model achieves 79% accuracy."',
            "The checkpoint supports a 128k context window.",
        ],
    )
    event_id = str(event.id)
    db.close()

    listed = client.get("/api/v1/events/").json()[0]
    detail = client.get(f"/api/v1/events/{event_id}").json()
    assert listed["citations"] == [
        "The model achieves 79% accuracy.",
        "The checkpoint supports a 128k context window.",
    ]
    assert detail["citations"] == listed["citations"]
    assert not any(item.startswith('"') or item.endswith('"') for item in detail["citations"])


def test_api_image_role_from_url_evidence():
    db = _TestingSessionLocal()
    source = _make_source(db)
    hero = _make_event(
        db, source,
        headline="NVIDIA photo",
        image_url="https://blogs.nvidia.com/wp-content/uploads/2026/07/Nemotron_LangChain-scaled.jpg",
    )
    source_img = _make_event(
        db, source,
        headline="HF thumbnail",
        image_url="https://huggingface.co/blog/assets/funes/thumbnail.jpg",
    )
    none_img = _make_event(
        db, source,
        headline="GitHub chrome",
        image_url="https://opengraph.githubassets.com/abc/jemalloc/jemalloc",
    )
    missing = _make_event(db, source, headline="No image", image_url=None)
    db.close()

    by_id = {item["id"]: item for item in client.get("/api/v1/events/?limit=20").json()}
    assert by_id[str(hero.id)]["image_role"] == "hero"
    assert by_id[str(source_img.id)]["image_role"] == "source"
    assert by_id[str(none_img.id)]["image_role"] == "none"
    assert by_id[str(missing.id)]["image_role"] == "none"
    assert by_id[str(none_img.id)]["image_url"]  # URL still returned; UI decides not to display it


def test_week_scope_keeps_current_week_and_drops_older_and_offtopic():
    """The intelligence feed is the current week, newest first, AI developments only."""
    from app.core.feed import current_week_start

    db = _TestingSessionLocal()
    primary = _make_source(db, name="OpenAI Blog", url="https://openai.com/news/rss.xml")
    community = _make_source(
        db, name="Hacker News", url="https://news.ycombinator.com/rss"
    )
    community.tier = "community"
    db.commit()

    start = current_week_start()
    fresh = _make_event(
        db,
        primary,
        headline="OpenAI releases a new reasoning model",
        short_summary="OpenAI released a reasoning model with a longer context window.",
        event_time=start + datetime.timedelta(days=1, hours=3),
        importance_score=95,
    )
    later_minor = _make_event(
        db,
        primary,
        headline="A lab publishes a small benchmark",
        short_summary="The benchmark covers a narrow coding task.",
        event_time=start + datetime.timedelta(days=2, hours=1),
        importance_score=30,
    )
    older_pub = _make_event(
        db,
        primary,
        headline="OpenAI releases an older model",
        short_summary="An earlier model release from last month.",
        event_time=start - datetime.timedelta(days=2),
        importance_score=95,
        created_at=start + datetime.timedelta(hours=1),
    )
    offtopic = _make_event(
        db,
        community,
        headline="People Turn to Cigarettes to Quit Vaping",
        short_summary="A personal story about nicotine habits.",
        event_time=start + datetime.timedelta(days=1, hours=4),
        importance_score=90,
    )
    db.close()

    response = client.get("/api/v1/events/?scope=week&limit=50")
    assert response.status_code == 200
    headlines = [item["headline"] for item in response.json()]
    assert headlines == [
        "A lab publishes a small benchmark",
        "OpenAI releases a new reasoning model",
    ]
    assert str(fresh.id) and str(later_minor.id)
    assert older_pub.headline not in headlines
    assert offtopic.headline not in headlines

    # Default list still includes older and off-topic rows; week scope is opt-in.
    everything = [item["headline"] for item in client.get("/api/v1/events/?limit=20").json()]
    assert "OpenAI releases an older model" in everything
    assert "People Turn to Cigarettes to Quit Vaping" in everything


def test_same_development_counts_once_in_the_week_feed_and_keeps_evidence():
    """N articles about one development are one feed card, with every article still attached."""
    from app.core.consolidate import consolidate_safe_duplicates

    db = _TestingSessionLocal()
    source = _make_source(db, name="Metro Desk", url="https://metro.example/feed")
    source.tier = "secondary"
    now = datetime.datetime.now(datetime.timezone.utc)
    headlines = [
        "Investigation reveals deaths near US-Mexico border surveillance towers",
        "Investigation reveals failures in US-Mexico border surveillance technology",
        "Surveillance technology fails to prevent migrant deaths at the U.S.-Mexico border",
        "New AI surveillance towers fail to prevent migrant deaths",
    ]
    urls = []
    for index, headline in enumerate(headlines):
        event = _make_event(
            db,
            source,
            headline=headline,
            short_summary="An investigation of AI surveillance along the border.",
            importance_score=70 + index,
            event_time=now,
            article_url=f"https://metro.example/border-{index}",
            importance_reasoning={"event_kind": "research"},
        )
        article = Article(
            id=uuid.uuid4(),
            source_id=source.id,
            url=f"https://metro.example/border-{index}",
            title=headline,
            raw_content="Border surveillance investigation.",
            hash=f"border-{index}",
            published_at=now,
        )
        db.add(article)
        db.flush()
        db.add(EventArticle(event_id=event.id, article_id=article.id, link_type="primary"))
        urls.append(article.url)
    db.commit()

    consolidate_safe_duplicates(db)
    db.close()

    listed = client.get("/api/v1/events/?scope=week&limit=50")
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    detail = client.get(f"/api/v1/events/{body[0]['id']}")
    assert detail.status_code == 200
    found = {item["url"] for item in detail.json()["linked_articles"]}
    assert found == set(urls)
