"""
Phase 1B, second attack pass, Area D (article_body enrichment path).

Explicit instruction for this area: do not assume the decompression-bomb
fix (INGEST-DECOMPRESSION-BOMB-01, docs/RED_TEAM_REPORT.md) is inherited
by app/core/article_body.py's enrich_article() merely because it calls a
fetch_fn that defaults to app.core.fetcher.fetch_url in production
(app/core/pipeline.py). Every existing test in test_article_body.py
passes a hand-rolled mock fetch_fn — none of them exercise the real
fetch_url() at all, so the inheritance was genuinely unverified.

This file calls enrich_article() with fetch_fn=fetch_url (the real
function; only the httpx transport is faked, exactly like
test_decompression_bomb.py's own proof technique), through the real
entrypoint article_body.py actually uses in production.
"""
import gzip

import httpx
import pytest
from unittest.mock import patch

from app.core.article_body import enrich_article, MIN_CONTENT_CHARS
from app.core.fetcher import fetch_url, MAX_RESPONSE_BYTES


class _GzipTransport(httpx.BaseTransport):
    """Same technique as test_decompression_bomb.py's GzipBombTransport —
    serves genuinely gzip-compressed content with a real Content-Encoding
    header, so decompression actually happens on the real code path."""

    def __init__(self, decompressed_body: bytes, content_type: str = "text/html"):
        self.compressed = gzip.compress(decompressed_body)
        self.content_type = content_type

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(self.compressed)),
                "content-type": self.content_type,
            },
            content=self.compressed,
        )


def test_enrich_article_rejects_gzip_bomb_via_real_fetch_url():
    """
    A feed entry with a too-short body triggers enrich_article() to fetch
    the article page. That page is a genuine gzip bomb (small on the wire,
    huge decompressed) served through the real fetch_url(). enrich_article
    must not hang, must not propagate the ValueError fetch_url raises, and
    must fall back to the original feed text rather than ever holding the
    decompressed bomb in memory.
    """
    decompressed_size = MAX_RESPONSE_BYTES * 20
    transport = _GzipTransport(b"A" * decompressed_size)
    assert len(transport.compressed) < MAX_RESPONSE_BYTES, (
        "test setup: compressed wire size must be small enough that only the "
        "decompression-aware cap (not the Content-Length pre-check) catches this"
    )
    fake_client = httpx.Client(transport=transport, follow_redirects=False)

    title = "Short feed title"
    short_body = "too short"  # under MIN_CONTENT_CHARS, forces the fetch path
    assert len(short_body) < MIN_CONTENT_CHARS

    with patch("app.core.fetcher.httpx.Client", return_value=fake_client):
        with patch("app.core.fetcher.pin_host"):
            content, image, publisher = enrich_article(
                title, "http://gzipbomb.example.com/article", short_body, None, fetch_fn=fetch_url
            )

    # enrich_article never raises (see its own docstring) — the ValueError
    # from fetch_url must have been caught internally and treated as a
    # failed fetch, falling back to the original feed-derived text.
    assert content == f"{title}. {short_body}"
    assert publisher is None


def test_enrich_article_succeeds_with_normal_gzip_article_via_real_fetch_url():
    """
    Neighboring/contrast case: a genuinely small, honestly gzip-compressed
    article page (the common real-world case) must still enrich correctly
    end-to-end through the real fetch_url(), including extracting the main
    article content and publisher name from the fetched HTML.
    """
    html = (
        "<html><head>"
        '<meta property="og:site_name" content="Real Publisher Corp">'
        "</head><body><nav>skip this nav chrome</nav>"
        "<article><p>"
        + ("This is the real article body fetched from the page. " * 5)
        + "</p></article></body></html>"
    )
    transport = _GzipTransport(html.encode("utf-8"))
    fake_client = httpx.Client(transport=transport, follow_redirects=False)

    title = "Short feed title"
    short_body = "too short"
    assert len(short_body) < MIN_CONTENT_CHARS

    with patch("app.core.fetcher.httpx.Client", return_value=fake_client):
        with patch("app.core.fetcher.pin_host"):
            content, image, publisher = enrich_article(
                title, "http://realarticle.example.com/post", short_body, None, fetch_fn=fetch_url
            )

    assert "real article body fetched from the page" in content
    assert "skip this nav chrome" not in content
    assert publisher == "Real Publisher Corp"
