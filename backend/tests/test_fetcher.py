"""
Tests for the fetcher SSRF protection.

The is_safe_url function is the last line of defense against Server-Side Request Forgery.
It must reject URLs that resolve to private/loopback/link-local/multicast IPs.

These tests use real DNS resolution when testing public domains (or mock it for private
IP ranges). We test the deterministic rejection logic directly.
"""
import socket
import ipaddress
from unittest.mock import patch
import pytest
from unittest.mock import MagicMock
from app.core.fetcher import (
    is_safe_url,
    pin_host,
    unpin_all,
    resolve_validated_addrinfo,
    _reject_oversized,
)
from app.core import fetcher as fetcher_mod


def _mock_getaddrinfo(hostname, port, results):
    """
    Helper to patch socket.getaddrinfo to return a controlled list of IP addresses.
    results: list of IP address strings, e.g. ['192.168.1.1', '::1']
    """
    # getaddrinfo returns (family, type, proto, canonname, sockaddr)
    # sockaddr for IPv4 is (ip, port), for IPv6 is (ip, port, flowinfo, scopeid)
    mock_results = []
    for ip in results:
        try:
            addr = ipaddress.ip_address(ip)
            if addr.version == 4:
                mock_results.append((socket.AF_INET, socket.SOCK_STREAM, 0, '', (ip, 0)))
            else:
                mock_results.append((socket.AF_INET6, socket.SOCK_STREAM, 0, '', (ip, 0, 0, 0)))
        except ValueError:
            pass
    return mock_results


class TestSsrfProtection:
    """SSRF protection must block all non-routable / private IP ranges."""

    def test_rejects_ipv4_loopback(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['127.0.0.1'])):
            assert is_safe_url("http://localhost/secret") is False

    def test_rejects_ipv4_private_class_a(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['10.0.0.1'])):
            assert is_safe_url("http://internal.corp/api") is False

    def test_rejects_ipv4_private_class_b(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['172.16.0.1'])):
            assert is_safe_url("http://internal-service/data") is False

    def test_rejects_ipv4_private_class_c(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['192.168.1.100'])):
            assert is_safe_url("http://homeserver/api/secret") is False

    def test_rejects_ipv4_link_local(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['169.254.169.254'])):
            assert is_safe_url("http://169.254.169.254/latest/meta-data/") is False

    def test_rejects_ipv6_loopback(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['::1'])):
            assert is_safe_url("http://[::1]/secret") is False

    def test_rejects_non_http_scheme(self):
        # No socket.getaddrinfo mock needed — scheme check comes first in normalize_url;
        # is_safe_url checks the scheme itself too.
        assert is_safe_url("ftp://example.com/file") is False
        assert is_safe_url("file:///etc/passwd") is False
        assert is_safe_url("gopher://evil.example.com") is False

    def test_rejects_empty_url(self):
        assert is_safe_url("") is False

    def test_rejects_url_with_no_hostname(self):
        assert is_safe_url("http:///path/only") is False

    def test_accepts_public_ip(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['1.1.1.1'])):
            assert is_safe_url("https://cloudflare.com/") is True

    def test_rejects_if_any_resolved_ip_is_private(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['1.2.3.4', '192.168.1.1'])):
            assert is_safe_url("https://tricky.example.com/") is False

    def test_rejects_unspecified_and_ipv4_mapped_loopback(self):
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['0.0.0.0'])):
            assert is_safe_url("http://0.0.0.0/") is False
        with patch('app.core.fetcher._original_getaddrinfo', return_value=_mock_getaddrinfo('', None, ['::ffff:127.0.0.1'])):
            assert is_safe_url("http://mapped.example/") is False

    def test_pin_host_stores_validated_records(self):
        records = _mock_getaddrinfo('', None, ['1.1.1.1'])
        with patch('app.core.fetcher._original_getaddrinfo', return_value=records):
            pin_host("cdn.example.com")
            try:
                pinned = fetcher_mod._tls.pin
                assert "cdn.example.com" in pinned
                # Pinned getaddrinfo must return the validated IP, not a rebound one
                fetcher_mod._ensure_hook()
                result = fetcher_mod._pinned_getaddrinfo("cdn.example.com", 443)
                assert result[0][4][0] == "1.1.1.1"
                assert result[0][4][1] == 443
            finally:
                unpin_all()

    def test_pin_host_rejects_private_resolution(self):
        records = _mock_getaddrinfo('', None, ['127.0.0.1'])
        with patch('app.core.fetcher._original_getaddrinfo', return_value=records):
            try:
                resolve_validated_addrinfo("evil.example")
                assert False, "should have raised"
            except ValueError as exc:
                assert "127.0.0.1" in str(exc)


def test_reject_oversized_respects_content_length():
    resp = MagicMock()
    resp.headers = {"content-length": "3000000"}
    resp.content = b"x"
    with pytest.raises(ValueError, match="too large"):
        _reject_oversized(resp)


def test_reject_oversized_respects_body_len():
    resp = MagicMock()
    resp.headers = {}
    resp.content = b"x" * (2_000_001)
    with pytest.raises(ValueError, match="too large"):
        _reject_oversized(resp)
