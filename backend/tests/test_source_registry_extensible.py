"""
A source added only as registry data is picked up by the normal scheduler.

The fixture feed is a local HTTP server. DNS pinning is stubbed so the real
fetcher can reach it; SSRF still rejects loopback addresses in production.
"""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from app.core.registry import RegistryError, upsert_source
from app.core.scheduler import IngestionScheduler
from app.models.article import Article
from app.models.event import Event
from app.models.source import Source


EMPTY_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>
"""

RESEARCH_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>OpenAI Research</title>
<item>
<title>OpenAI Research publishes a benchmark dataset for agents</title>
<link>https://example.com/openai-research/agent-benchmark-dataset</link>
<description>OpenAI Research published a benchmark dataset covering agent evaluation, tool use, and model comparison across several tasks.</description>
</item>
</channel></rss>
"""


class _FeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        server = self.server
        server.hits.append(self.path)  # type: ignore[attr-defined]
        if self.path.startswith("/fail"):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"missing")
            return
        body = RESEARCH_RSS if self.path.startswith("/research") else EMPTY_RSS
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def _start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FeedHandler)
    server.hits = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _pin_localhost(_hostname: str):
    return socket.getaddrinfo("127.0.0.1", None)


def _disable_preexisting(db_session):
    for row in db_session.query(Source).all():
        row.enabled = False
    db_session.commit()


def test_registry_rejects_non_public_urls(db_session):
    for url in ("javascript:alert(1)", "file:///tmp/feed.xml", "http://127.0.0.1/rss"):
        try:
            upsert_source(
                db_session,
                organization="Example",
                name="Bad",
                url=url,
            )
        except RegistryError:
            continue
        raise AssertionError(f"accepted unsafe url {url}")


def test_duplicate_add_and_url_update_stay_one_row(db_session):
    first, action = upsert_source(
        db_session,
        organization="OpenAI",
        name="OpenAI Research",
        url="https://example.com/research/feed.xml",
        tier="research",
        enabled=True,
        update_enabled=True,
    )
    db_session.commit()
    assert action == "inserted"
    again, action = upsert_source(
        db_session,
        organization="OpenAI",
        name="OpenAI Research",
        url="https://example.com/research/feed.xml",
        tier="research",
        enabled=True,
        update_enabled=True,
    )
    db_session.commit()
    assert action == "updated"
    assert again.id == first.id
    moved, _action = upsert_source(
        db_session,
        organization="OpenAI",
        name="OpenAI Research",
        url="https://example.com/research/feed-v2.xml",
        tier="research",
        update_enabled=False,
    )
    db_session.commit()
    assert moved.id == first.id
    assert moved.url == "https://example.com/research/feed-v2.xml"
    assert db_session.query(Source).filter(Source.name == "OpenAI Research").count() == 1


def test_enabled_source_is_fetched_and_disabled_source_is_not(db_session):
    _disable_preexisting(db_session)
    server = _start_server()
    port = server.server_address[1]
    host = f"http://fixture.feed.test:{port}"
    try:
        enabled, _ = upsert_source(
            db_session,
            organization="OpenAI",
            name="OpenAI Research",
            url=f"{host}/research.xml",
            tier="research",
            enabled=True,
            update_enabled=True,
        )
        upsert_source(
            db_session,
            organization="OpenAI",
            name="OpenAI Research Off",
            url=f"{host}/disabled.xml",
            tier="research",
            enabled=False,
            update_enabled=True,
        )
        db_session.commit()
        enabled_id = enabled.id
        db_session.close = MagicMock()

        scheduler = IngestionScheduler()
        with patch("app.core.scheduler.SessionLocal", return_value=db_session):
            with patch("app.core.fetcher.resolve_validated_addrinfo", _pin_localhost):
                scheduler.run_ingestion_cycle()

        hits = server.hits
        assert any(path.startswith("/research") for path in hits)
        assert not any(path.startswith("/disabled") for path in hits)

        db_session.expire_all()
        article = (
            db_session.query(Article)
            .filter(Article.source_id == enabled_id)
            .one()
        )
        assert article.url.startswith("https://example.com/openai-research/")
        event = db_session.query(Event).filter(Event.primary_source_id == enabled_id).one()
        assert event.headline
        assert event.short_summary
        assert event.article_url == article.url
    finally:
        server.shutdown()


def test_one_failing_source_does_not_stop_a_larger_registry(db_session):
    _disable_preexisting(db_session)
    server = _start_server()
    port = server.server_address[1]
    host = f"http://fixture.feed.test:{port}"
    try:
        ids = []
        for index in range(40):
            path = "/fail.xml" if index == 7 else f"/ok/{index}.xml"
            source, _ = upsert_source(
                db_session,
                organization="Lab",
                name=f"Lab Feed {index}",
                url=f"{host}{path}",
                tier="research",
                enabled=True,
                update_enabled=True,
            )
            ids.append(source.id)
        db_session.commit()
        db_session.close = MagicMock()

        started = time.perf_counter()
        scheduler = IngestionScheduler()
        with patch("app.core.scheduler.SessionLocal", return_value=db_session):
            with patch("app.core.fetcher.resolve_validated_addrinfo", _pin_localhost):
                scheduler.run_ingestion_cycle()
        elapsed = time.perf_counter() - started

        db_session.expire_all()
        rows = db_session.query(Source).filter(Source.id.in_(ids)).all()
        failing = [row for row in rows if row.health_status == "failing"]
        healthy = [row for row in rows if row.health_status == "healthy"]
        assert len(failing) == 1
        assert len(healthy) == 39
        assert len(server.hits) == 40
        assert elapsed < 45, f"40-source cycle took {elapsed:.1f}s"
    finally:
        server.shutdown()


def test_changing_a_source_url_clears_the_old_urls_failure_history(db_session):
    """A replaced dead feed must be fetched on the next tick, not after hours of backoff."""
    from datetime import datetime, timezone

    from app.core.scheduler import is_source_due

    source, _ = upsert_source(
        db_session, organization="Meta AI", name="Meta AI Research",
        url="https://ai.meta.com/blog/rss", tier="primary", enabled=True, update_enabled=True,
    )
    source.health_status = "failing"
    source.consecutive_failures = 4
    source.last_failure_at = datetime.now(timezone.utc)
    source.last_error_info = "Client error '404 Not Found'"
    db_session.commit()
    assert not is_source_due(source)

    moved, action = upsert_source(
        db_session, organization="Meta AI", name="Meta AI Research",
        url="https://engineering.fb.com/category/ai-research/feed/", tier="primary", enabled=True,
    )
    db_session.commit()
    assert action == "updated"
    assert moved.consecutive_failures == 0
    assert moved.last_error_info is None
    assert moved.health_status == "healthy"
    assert is_source_due(moved)

    # Re-saving the same URL keeps real history.
    moved.consecutive_failures = 2
    db_session.commit()
    again, _ = upsert_source(
        db_session, organization="Meta AI", name="Meta AI Research",
        url="https://engineering.fb.com/category/ai-research/feed/", tier="primary", enabled=True,
    )
    assert again.consecutive_failures == 2
