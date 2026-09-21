"""
Sanitization of untrusted URLs from RSS/Atom/HTML sources.

Used for article links (stored, shown as Official Source) and image URLs
(rendered in <img src>). Anything that is not a clean public http(s) URL
is rejected as empty string.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse, urlunparse, unquote

_SAFE_SCHEMES = {"http", "https"}
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.google.internal.",
}

# Ports that must never be used as article/image/fetch targets.
_BLOCKED_PORTS = {
    20, 21, 22, 23, 25, 69, 110, 135, 137, 138, 139, 143, 161, 389, 445,
    1433, 1521, 2049, 3306, 3389, 5432, 5900, 6379, 9200, 9300, 11211, 27017,
}

# javascript: / data: / vbscript: even when padded or mixed-case
_DANGEROUS_SCHEME_RE = re.compile(
    r"^\s*(?:javascript|data|vbscript|file|ftp|gopher|ws|wss)\s*:",
    re.IGNORECASE,
)


def is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """True if this IP must never be used as a fetch or display target."""
    if ip.version == 6 and getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _is_ip_literal_trick(host: str) -> bool:
    """
    Browsers accept decimal (2130706433), hex (0x7f000001), and short
    (127.1) IPv4 forms as 127.0.0.1. Reject them before they reach fetch/UI.
    """
    if not host:
        return True
    if host.startswith("0x"):
        return True
    if host.isdigit():
        return True
    parts = host.split(".")
    if 1 <= len(parts) <= 4 and all(
        p.isdigit() or p.lower().startswith("0x") for p in parts
    ):
        if len(parts) < 4:
            return True
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return True
    return False


def is_blocked_hostname(hostname: str) -> bool:
    """
    Block literal loopback/private hosts without DNS.
    Domain names that later resolve privately are blocked at fetch time.
    """
    if not hostname:
        return True
    host = hostname.strip().strip("[]").lower().rstrip(".")
    if host in _BLOCKED_HOSTS:
        return True
    if host.endswith(".localhost") or host.endswith(".local"):
        return True
    if _is_ip_literal_trick(host):
        try:
            return is_blocked_ip(ipaddress.ip_address(host))
        except ValueError:
            return True
    try:
        return is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        return False


def sanitize_http_url(url: str | None, *, keep_query: bool = False) -> str:
    """
    Return a canonical http(s) URL suitable for storage and frontend use,
    or "" if the URL is missing, malformed, or unsafe.

    Rejects:
    - non-http(s) schemes (javascript:, data:, file:, ftp:, ...)
    - scheme-relative URLs (//evil.com)
    - credentials in the netloc (user:pass@host)
    - literal private/loopback/link-local IP hosts
    - empty or missing hostname

    keep_query: article URLs strip query/fragment for dedup. Image/CDN URLs
    must keep query strings (signed URLs, size params).
    """
    if not url or not isinstance(url, str):
        return ""

    raw = url.strip()
    if not raw:
        return ""

    # Reject dangerous schemes before urlparse (handles "javascript:alert(1)"
    # and padded variants). Percent-encoded schemes are decoded first.
    decoded_head = unquote(raw[:32])
    if _DANGEROUS_SCHEME_RE.match(raw) or _DANGEROUS_SCHEME_RE.match(decoded_head):
        return ""

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _SAFE_SCHEMES:
        return ""

    hostname = parsed.hostname
    if not hostname:
        return ""

    if parsed.port and parsed.port in _BLOCKED_PORTS:
        return ""

    if is_blocked_hostname(hostname):
        return ""

    # Rebuild netloc WITHOUT userinfo (credentials are never stored or shown)
    host = hostname.lower()
    if parsed.port:
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]:{parsed.port}"
        else:
            netloc = f"{host}:{parsed.port}"
    else:
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]"
        else:
            netloc = host

    path = parsed.path
    if not keep_query:
        path = path.rstrip("/") if path != "/" else ""

    canonical = urlunparse((
        scheme,
        netloc,
        path,
        "",
        parsed.query if keep_query else "",
        "",
    ))
    return canonical
