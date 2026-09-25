import pytest
from unittest.mock import patch, MagicMock
import httpx
from app.core.fetcher import fetch_url
from app.core.urls import sanitize_http_url


class MockRedirectResponse:
    """
    Usable as the context-manager result of `client.stream(...)` —
    fetch_url() streams (`with client.stream("GET", ...) as streamed:`),
    not client.get(), since INGEST-DECOMPRESSION-BOMB-01
    (docs/security-findings.md): reading with an incrementally-capped
    stream instead of a fully-materialized client.get() response is what
    actually closes that gap. Mocking must therefore patch
    `httpx.Client.stream`, not `httpx.Client.get`.
    """

    def __init__(self, location, status_code=302):
        self.status_code = status_code
        self.headers = {"Location": location} if location else {}
        self.content = b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        return iter([])


def test_fetch_url_redirect_to_private():
    # Setup mock to return a redirect to a private IP
    def mock_stream(method, url, **kwargs):
        if url == "http://public.com":
            return MockRedirectResponse("http://192.168.1.1")
        elif url == "http://192.168.1.1":
            return MockRedirectResponse("", status_code=200)  # Should not be reached
        raise ValueError(f"Unexpected URL: {url}")

    with patch('httpx.Client.stream', side_effect=mock_stream):
        with patch('app.core.fetcher.pin_host') as mock_pin_host:
            # pin_host will normally raise ValueError if it resolves to private,
            # but since 192.168.1.1 is caught by sanitize_http_url, pin_host won't even be called for it.
            with pytest.raises(ValueError, match="Unsafe URL"):
                fetch_url("http://public.com")


def test_fetch_url_redirect_to_dns_rebinding():
    # Setup mock to return a redirect to a domain that resolves to private IP
    # We will simulate pin_host raising ValueError for the second domain
    def mock_stream(method, url, **kwargs):
        if url == "http://public.com":
            return MockRedirectResponse("http://evil-dns.com")
        return MockRedirectResponse("", status_code=200)

    def mock_pin(hostname):
        if hostname == "evil-dns.com":
            raise ValueError("Unsafe URL host evil-dns.com resolved to blocked IP")
        return None

    with patch('httpx.Client.stream', side_effect=mock_stream):
        with patch('app.core.fetcher.pin_host', side_effect=mock_pin):
            with pytest.raises(ValueError, match="Unsafe URL"):
                fetch_url("http://public.com")
