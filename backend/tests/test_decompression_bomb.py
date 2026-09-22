"""
Phase 1B, invariant 6 (response size limits) — INGEST-DECOMPRESSION-BOMB-01
(docs/RED_TEAM_REPORT.md).

Reproduced directly (not assumed) before fixing: a 48KB gzip-compressed
payload decompressing to 50MB was fully materialized in memory via
httpx's `response.content` BEFORE `_reject_oversized`'s post-hoc length
check ever ran — the Content-Length header check alone is insufficient
because it reflects the compressed wire size, not the eventual
decompressed size.

This file proves the fix end-to-end through the real `fetch_url()`
entrypoint (not just the isolated `_read_body_with_cap`/
`_headers_for_already_decoded_body` unit tests in test_fetcher.py),
using a fake httpx transport that serves a genuinely compressed,
massively-expanding gzip body — the same class of proof technique
already established this session for the timeout-bound work
(TrickleTransport in test_nvidia_timeout_bound.py).
"""
import gzip

import httpx
import pytest
from unittest.mock import patch

from app.core.fetcher import fetch_url, MAX_RESPONSE_BYTES


class GzipBombTransport(httpx.BaseTransport):
    """Serves a small compressed payload that decompresses far past
    MAX_RESPONSE_BYTES, with a real gzip Content-Encoding header — this
    is what makes it a genuine test of the decompression path, not just
    an oversized-plain-body test (already covered by test_fetcher.py's
    _read_body_with_cap tests)."""

    def __init__(self, decompressed_size: int):
        huge = b"A" * decompressed_size
        self.compressed = gzip.compress(huge)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-encoding": "gzip",
                "content-length": str(len(self.compressed)),
                "content-type": "application/rss+xml",
            },
            content=self.compressed,
        )


def test_fetch_url_rejects_gzip_bomb_via_real_entrypoint():
    """
    A 50MB-decompressed gzip bomb, compressed down to well under
    MAX_RESPONSE_BYTES on the wire (so the Content-Length pre-check alone
    would pass it through) must still be rejected by fetch_url() — proven
    against the real function, with only the transport layer faked.
    """
    decompressed_size = MAX_RESPONSE_BYTES * 20  # far past the cap once expanded
    transport = GzipBombTransport(decompressed_size)
    assert len(transport.compressed) < MAX_RESPONSE_BYTES, (
        "test setup: the compressed wire size must itself be small enough that only "
        "the decompression-aware check (not the Content-Length pre-check) catches this"
    )

    fake_client = httpx.Client(transport=transport, follow_redirects=False)

    with patch("app.core.fetcher.httpx.Client", return_value=fake_client):
        with patch("app.core.fetcher.pin_host"):
            with pytest.raises(ValueError, match="too large"):
                fetch_url("http://gzipbomb.example.com/rss")


def test_fetch_url_accepts_normal_gzip_compressed_response():
    """
    Neighboring/contrast case: a genuinely small, honestly-compressed
    response (the overwhelmingly common real-world case — most real feed
    servers gzip their responses) must still work correctly end-to-end,
    including the Content-Encoding-stripping fix in
    _headers_for_already_decoded_body (a real bug this session's own
    "attack the fix" step caught: reconstructing a Response with the
    original Content-Encoding header alongside an already-decoded body
    corrupted real compressed responses).
    """
    real_feed_xml = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>'
        "<item><title>A</title><link>https://example.com/a</link>"
        "<description>Enough content to be a real entry.</description></item>"
        "</channel></rss>"
    )
    transport = GzipBombTransport(0)  # placeholder, overwritten below
    transport.compressed = gzip.compress(real_feed_xml.encode("utf-8"))

    fake_client = httpx.Client(transport=transport, follow_redirects=False)

    with patch("app.core.fetcher.httpx.Client", return_value=fake_client):
        with patch("app.core.fetcher.pin_host"):
            response = fetch_url("http://realfeed.example.com/rss")

    assert response.status_code == 200
    assert "<title>Test</title>" in response.text
