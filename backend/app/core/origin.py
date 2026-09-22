"""
Ingest source vs originating/official source.

Never invent a publisher from a domain string alone.
Publisher name must come from page evidence (og:site_name, JSON-LD publisher)
or from the ingest source when the article is native to that source.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional
from urllib.parse import urlparse

from app.core.urls import sanitize_http_url

AGGREGATOR_HOSTS = {
    "news.ycombinator.com",
    "hnrss.org",
    "reddit.com",
    "www.reddit.com",
    "old.reddit.com",
    "news.google.com",
}

_OG_SITE = (
    re.compile(
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:site_name["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']application-name["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
)

_JSONLD_PUBLISHER = re.compile(
    r'"publisher"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"name"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)

# Not a full Public Suffix List (no dependency added for it) — the
# multi-label suffixes real-world news publishers are most likely to sit
# under. Anything else falls back to the last-2-labels heuristic below,
# which is correct for the common case (.com/.org/.net/single-label TLDs).
_MULTI_LABEL_PUBLIC_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk", "ltd.uk", "plc.uk",
    "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
    "co.kr", "or.kr", "ne.kr",
    "co.nz", "org.nz", "govt.nz", "ac.nz",
    "co.za", "org.za", "gov.za",
    "com.au", "net.au", "org.au", "gov.au", "edu.au",
    "com.br", "net.br", "org.br", "gov.br",
    "com.mx", "gob.mx",
    "co.in", "net.in", "org.in", "gov.in", "ac.in",
    "co.il", "org.il", "gov.il",
    "co.id", "or.id", "go.id",
    "com.sg", "gov.sg", "edu.sg",
    "com.hk", "gov.hk", "org.hk", "edu.hk",
}


class OriginResolution(NamedTuple):
    ingest_name: Optional[str]
    ingest_url: Optional[str]
    official_name: Optional[str]
    official_url: Optional[str]
    display_name: Optional[str]
    display_url: Optional[str]
    used_official: bool


def host_of(url: Optional[str]) -> str:
    if not url:
        return ""
    return (urlparse(url).netloc or "").lower().removeprefix("www.")


def is_aggregator_host(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    if host in AGGREGATOR_HOSTS:
        return True
    return any(host.endswith("." + item) for item in AGGREGATOR_HOSTS)


def is_aggregator_source(name: Optional[str], url: Optional[str]) -> bool:
    if is_aggregator_host(host_of(url)):
        return True
    n = (name or "").strip().lower()
    return n in {"hacker news", "hn", "reddit", "google news"}


def same_registrable_host(a: str, b: str) -> bool:
    """
    Compare registrable domains, not raw hostnames, so `blog.example.com`
    and `example.com` count as the same site.

    A naive last-2-labels comparison breaks for hosts under a multi-label
    public suffix (`.co.uk`, `.com.au`, ...): `bbc.co.uk` and `evil.co.uk`
    both reduce to `("co", "uk")` and would wrongly compare equal, even
    though `.co.uk` is a public suffix, not a registrable domain, and
    these are two unrelated sites. Reproduced directly against this
    function before fixing. See docs/RED_TEAM_REPORT.md for the finding
    this fix addresses.
    """
    def parts(host: str) -> tuple[str, ...]:
        bits = [p for p in host.lower().removeprefix("www.").split(".") if p]
        if len(bits) >= 3 and ".".join(bits[-2:]) in _MULTI_LABEL_PUBLIC_SUFFIXES:
            return tuple(bits[-3:])
        return tuple(bits[-2:]) if len(bits) >= 2 else tuple(bits)

    pa, pb = parts(a), parts(b)
    return bool(pa and pb and pa == pb)


def extract_publisher_from_html(html: Optional[str]) -> str:
    if not html:
        return ""
    for pattern in _OG_SITE:
        match = pattern.search(html)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip()
            if name:
                return name[:120]
    match = _JSONLD_PUBLISHER.search(html)
    if match:
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        if name:
            return name[:120]
    return ""


def resolve_originating_source(
    *,
    ingest_name: Optional[str],
    ingest_url: Optional[str],
    article_url: Optional[str],
    publisher_name: Optional[str] = None,
) -> OriginResolution:
    """
    Prefer a confidently established originating publisher for display.

    Confidence requires:
    - ingest is an aggregator, AND
    - article_url is a different site, AND
    - publisher_name came from page evidence (not from the domain).
    """
    ingest_name = (ingest_name or "").strip() or None
    ingest_url = sanitize_http_url(ingest_url) or ingest_url
    article_url = sanitize_http_url(article_url) or article_url
    publisher = (publisher_name or "").strip() or None

    ingest_host = host_of(ingest_url)
    article_host = host_of(article_url)
    aggregator = is_aggregator_source(ingest_name, ingest_url)
    different_site = bool(
        article_host
        and ingest_host
        and not same_registrable_host(ingest_host, article_host)
        and not is_aggregator_host(article_host)
    )

    if aggregator and different_site and publisher:
        return OriginResolution(
            ingest_name=ingest_name,
            ingest_url=ingest_url,
            official_name=publisher,
            official_url=article_url,
            display_name=publisher,
            display_url=article_url,
            used_official=True,
        )

    # Native blog / official feed: ingest IS the origin.
    return OriginResolution(
        ingest_name=ingest_name,
        ingest_url=ingest_url,
        official_name=ingest_name if not (aggregator and different_site) else None,
        official_url=article_url or ingest_url,
        display_name=ingest_name,
        display_url=article_url or ingest_url,
        used_official=False,
    )
