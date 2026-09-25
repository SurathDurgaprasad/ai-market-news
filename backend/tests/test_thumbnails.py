"""
Card thumbnails: a 96x64 slot used to download the publisher's full image
(often 1-3 MB). The API now serves a small cached WebP, fetched only from
the URL stored for the event, never from a URL in the request.
"""
import uuid
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core import thumbnails
from app.db.session import get_db
from app.main import app
from app.models.event import Event
from app.models.source import Source


def _png(width, height):
    out = BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _isolated(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path / "cache"))
    previous = app.dependency_overrides.get(get_db)

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    if previous is not None:
        app.dependency_overrides[get_db] = previous
    else:
        app.dependency_overrides.pop(get_db, None)


def _event(db_session, image_url):
    source = db_session.query(Source).first()
    event = Event(id=uuid.uuid4(), headline="Lab ships model", short_summary="It shipped.",
                  primary_source_id=source.id, version=1, importance_score=60, image_url=image_url)
    db_session.add(event)
    db_session.commit()
    return event


def test_resize_makes_a_small_webp_and_never_upscales():
    small = thumbnails.resize_to_webp(_png(2400, 1600), 192)
    image = Image.open(BytesIO(small))
    assert image.format == "WEBP" and image.size == (192, 128)
    assert len(small) < 5_000
    assert Image.open(BytesIO(thumbnails.resize_to_webp(_png(100, 50), 640))).size == (100, 50)


def test_non_raster_and_oversized_images_are_refused():
    assert thumbnails.resize_to_webp(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", 192) is None
    assert thumbnails.resize_to_webp(b"not an image", 192) is None
    # A decompression bomb: a tiny file declaring 20000 x 20000 pixels.
    bomb = BytesIO()
    Image.new("1", (20000, 20000)).save(bomb, format="PNG")
    assert thumbnails.resize_to_webp(bomb.getvalue(), 192) is None


def test_private_addresses_are_never_fetched():
    assert thumbnails._fetch_source("http://127.0.0.1/admin.png") is None
    assert thumbnails._fetch_source("http://169.254.169.254/latest/meta-data/") is None
    assert thumbnails._fetch_source("http://[::1]/x.png") is None


def test_endpoint_serves_the_stored_image_resized_and_cached(db_session, monkeypatch):
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return _png(1600, 900)

    monkeypatch.setattr(thumbnails, "_fetch_source", fake_fetch)
    event = _event(db_session, "https://cdn.example.com/photo.jpg")
    client = TestClient(app)
    first = client.get(f"/api/v1/events/{event.id}/image?w=180")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/webp"
    assert "nosniff" in first.headers["x-content-type-options"]
    assert Image.open(BytesIO(first.content)).size == (192, 108)  # nearest allowed width
    second = client.get(f"/api/v1/events/{event.id}/image?w=180")
    assert second.content == first.content
    assert fetched == ["https://cdn.example.com/photo.jpg"]        # fetched once, then cached


def test_endpoint_ignores_request_urls_and_rejects_missing_images(db_session, monkeypatch):
    fetched = []
    monkeypatch.setattr(thumbnails, "_fetch_source", lambda url: fetched.append(url) or _png(10, 10))
    client = TestClient(app)
    no_image = _event(db_session, None)
    assert client.get(f"/api/v1/events/{no_image.id}/image").status_code == 404
    chrome = _event(db_session, "https://opengraph.githubassets.com/abc/repo")
    assert client.get(f"/api/v1/events/{chrome.id}/image").status_code == 404
    assert client.get("/api/v1/events/not-a-uuid/image").status_code == 404
    real = _event(db_session, "https://cdn.example.com/a.png")
    client.get(f"/api/v1/events/{real.id}/image?w=192&url=http://127.0.0.1/secret")
    assert fetched == ["https://cdn.example.com/a.png"]
