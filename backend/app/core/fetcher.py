"""
HTTP fetching with SSRF controls.

TOCTOU / DNS-rebinding mitigation
---------------------------------
is_safe_url used to resolve DNS, validate IPs, then let httpx resolve DNS
again for the actual TCP connect. Between those two lookups a malicious
authoritative DNS could switch from a public IP to 127.0.0.1.

This module resolves once, rejects the host if ANY address is blocked, then
pins socket.getaddrinfo for this thread so httpx connects to the validated
IPs only. Redirect hops are resolved and pinned independently.

Remaining limitation (documented, not claimed solved):
- We pin the IPs we resolved. We do not terminate TLS against a raw IP with
  independent SNI plumbing beyond what httpx does with the original hostname.
  Because getaddrinfo is pinned, the TCP peer is the validated IP and the
  Host/SNI header remains the original hostname — this is the intended bind.
- We cannot stop a compromised host from serving different content after
  connect. That is not SSRF.
"""
from __future__ import annotations

import logging
import threading
import socket
import ipaddress
from urllib.parse import urlparse, urljoin
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type, retry_if_result

from app.core.urls import is_blocked_ip, sanitize_http_url

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 2_000_000

_original_getaddrinfo = socket.getaddrinfo
_tls = threading.local()
_hook_installed = False
_hook_lock = threading.Lock()


def _adapt_addrinfo(records, port):
    adapted = []
    for family, type_, proto, canon, sockaddr in records:
        ip = sockaddr[0]
        if family == socket.AF_INET6:
            flow = sockaddr[2] if len(sockaddr) > 2 else 0
            scope = sockaddr[3] if len(sockaddr) > 3 else 0
            new_sa = (ip, port or 0, flow, scope)
        else:
            new_sa = (ip, port or 0)
        adapted.append((family, type_, proto, canon, new_sa))
    return adapted


def _pinned_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    pinned = getattr(_tls, "pin", None)
    key = (host or "").lower().rstrip(".")
    if pinned and key in pinned:
        return _adapt_addrinfo(pinned[key], port)
    return _original_getaddrinfo(host, port, family, type, proto, flags)


def _ensure_hook():
    global _hook_installed
    if _hook_installed:
        return
    with _hook_lock:
        if not _hook_installed:
            socket.getaddrinfo = _pinned_getaddrinfo
            _hook_installed = True


def resolve_validated_addrinfo(hostname: str) -> list:
    """
    Resolve hostname via the real getaddrinfo and reject the whole host if
    any returned address is private/loopback/link-local/multicast/reserved/
    unspecified, including IPv4-mapped IPv6.
    """
    if not hostname:
        raise ValueError("Empty hostname")
    try:
        results = _original_getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname}: {exc}") from exc

    if not results:
        raise ValueError(f"No addresses for {hostname}")

    for result in results:
        ip_str = result[4][0]
        ip = ipaddress.ip_address(ip_str)
        if is_blocked_ip(ip):
            raise ValueError(f"Unsafe URL host {hostname} resolved to blocked IP {ip_str}")
    return results


def is_safe_url(url: str) -> bool:
    """SSRF pre-check: scheme, hostname, and every resolved IP must be public."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        resolve_validated_addrinfo(hostname)
        return True
    except Exception as e:
        logger.error(f"SSRF check failed for {url}: {e}")
        return False


def pin_host(hostname: str) -> None:
    """Pin this thread's getaddrinfo for hostname to its validated IPs."""
    records = resolve_validated_addrinfo(hostname)
    current = getattr(_tls, "pin", None) or {}
    current[hostname.lower().rstrip(".")] = records
    _tls.pin = current


def unpin_all() -> None:
    _tls.pin = None


def is_transient_error(response: httpx.Response) -> bool:
    """Retry on 429 Too Many Requests or 5xx Server Errors"""
    return response.status_code == 429 or response.status_code >= 500


def _reject_oversized(response: httpx.Response) -> None:
    """
    Refuse feed/article payloads larger than MAX_RESPONSE_BYTES.

    Content-Length is checked first. The body is still loaded by httpx for
    responses that omit Content-Length; that residual case is bounded only
    after the bytes are in memory.
    """
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError:
            declared = None
        else:
            if declared > MAX_RESPONSE_BYTES:
                raise ValueError(f"Response too large ({declared} bytes)")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Response too large ({len(response.content)} bytes)")


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(4),
    retry=(
        retry_if_exception_type((httpx.RequestError, httpx.TimeoutException)) |
        retry_if_result(is_transient_error)
    ),
    reraise=True
)
def fetch_url(url: str, timeout: int = 15, max_redirects: int = 5) -> httpx.Response:
    """
    Fetch a URL with exponential backoff.

    Redirects are followed manually so every hop is SSRF-checked and DNS-pinned
    before connect. Raises if the URL is unsafe or retries are exhausted.
    """
    logger.info(f"Fetching URL: {url}")
    _ensure_hook()

    current_url = url
    headers = {
        "User-Agent": "AIWorldIntelligencePlatform/1.0 (feed-ingest)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            for _ in range(max_redirects + 1):
                sanitized = sanitize_http_url(current_url, keep_query=True)
                if not sanitized:
                    logger.error(f"SSRF protection blocked fetch for: {current_url}")
                    raise ValueError(f"Unsafe URL: {current_url}")

                parsed = urlparse(sanitized)
                try:
                    pin_host(parsed.hostname)
                except ValueError as exc:
                    logger.error(f"SSRF protection blocked fetch for: {current_url} ({exc})")
                    raise ValueError(f"Unsafe URL: {current_url}") from exc

                response = client.get(sanitized, headers=headers)

                if response.status_code in (301, 302, 303, 307, 308):
                    next_url = response.headers.get("Location")
                    if not next_url:
                        break
                    current_url = urljoin(sanitized, next_url)
                    logger.info(f"Following redirect to: {current_url}")
                    continue

                if is_transient_error(response):
                    logger.warning(f"Transient error {response.status_code} from {current_url}, retrying...")
                    return response

                response.raise_for_status()
                _reject_oversized(response)
                return response

            raise ValueError(f"Too many redirects for url: {url}")
    finally:
        unpin_all()
