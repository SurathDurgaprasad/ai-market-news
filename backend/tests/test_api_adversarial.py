import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db


@pytest.fixture(autouse=True)
def _override_get_db(db_session):
    """
    Point the shared `app` singleton's get_db dependency at this test's
    db_session, then restore prior state on teardown.

    Without the restore, `app.dependency_overrides[get_db]` is left
    pointing at a closed, table-dropped session after the last test in
    this file runs — corrupting any test file that executes afterward
    and shares the same `app` import (e.g. test_api_events.py, which sets
    its own override once at module-collection time and never expects it
    to be silently overwritten mid-session).
    """
    previous = app.dependency_overrides.get(get_db)

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    if previous is not None:
        app.dependency_overrides[get_db] = previous
    else:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client():
    return TestClient(app)


def test_api_pagination_limits(client):
    # Attempting to fetch 10,000 items at once should be rejected
    # because `limit` has an upper bound in FastAPI.
    response = client.get("/api/v1/events/?limit=10000")
    assert response.status_code == 422  # Unprocessable Entity


def test_api_deep_offset_attack(client):
    # The `skip` parameter has `ge=0` but NO upper bound.
    # An attacker can request an extremely deep offset (e.g. 1,000,000).
    # In SQLite/Postgres, this forces the DB to scan and discard 1M rows,
    # causing a CPU/IO spike and potential Denial of Service.
    # This is a KNOWN LIMITATION (lack of deep pagination protection or cursor pagination).
    response = client.get("/api/v1/events/?skip=1000000")
    # It will return 200 OK (with an empty list), proving the query ran successfully
    assert response.status_code == 200


def test_api_rate_limiting_missing(client):
    # There is no rate limiting on the /api/v1/events endpoint.
    # An attacker can spam the endpoint rapidly.
    # This is a KNOWN LIMITATION.
    for _ in range(50):
        response = client.get("/api/v1/events/?limit=1")
        assert response.status_code == 200


def test_api_sqli_in_search(client):
    # SQLAlchemy's `ilike` uses parameterized queries, preventing traditional SQLi.
    # However, passing wildcard characters directly into `q` can cause heavy LIKE queries.
    response = client.get("/api/v1/events/?q=%25%25%25%25%25%25")
    assert response.status_code == 200


def test_api_xss_in_payload(client, db_session):
    # If a malicious article was ingested with XSS in the headline,
    # the API returns it unescaped.
    # It is expected that the frontend escapes HTML when rendering JSON.
    from app.models.event import Event
    from uuid import uuid4
    from datetime import datetime, timezone

    from app.models.source import Source
    source = db_session.query(Source).first()

    event = Event(
        id=uuid4(),
        headline="<script>alert(1)</script>",
        short_summary="Summary",
        importance_score=50,
        primary_source_id=source.id,
        created_at=datetime.now(timezone.utc)
    )
    db_session.add(event)
    db_session.commit()

    response = client.get(f"/api/v1/events/{event.id}")
    assert response.status_code == 200
    assert "<script>alert(1)</script>" in response.json()["headline"]
