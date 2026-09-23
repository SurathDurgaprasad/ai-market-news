"""
Enrich short RSS/Atom entries with the article page when the feed body is empty.

Many real feeds (Hacker News, some Atom blogs) ship a title + URL and little or
no description. Dropping those at the 50-character gate silently discards
real events. Fetching the article URL (via the existing SSRF-protected
fetcher) is the correct fallback.

This module never raises: a failed page fetch leaves the caller with the
original title/body composition.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

MIN_CONTENT_CHARS = 50
MAX_CONTENT_CHARS = 40_000
MAX_HTML_BYTES = 1_000_000

_OG_IMAGE_PATTERNS = (
    re.compile(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        re.IGNORECASE,
    ),
)


def compose_feed_text(title: str, body: str) -> str:
    """Title + body, used when the feed body is missing or too short."""
    body = (body or "").strip()
    title = (title or "").strip()
    if len(body) >= MIN_CONTENT_CHARS:
        return body[:MAX_CONTENT_CHARS]
    if not title:
        return body[:MAX_CONTENT_CHARS]
    if not body:
        return title[:MAX_CONTENT_CHARS]
    return f"{title}. {body}"[:MAX_CONTENT_CHARS]


def extract_og_image(html: str) -> str:
    from app.core.urls import sanitize_http_url

    if not html:
        return ""
    for pattern in _OG_IMAGE_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        safe = sanitize_http_url(match.group(1), keep_query=True)
        if safe:
            return safe
    return ""


def extract_publisher_name(html: str) -> str:
    from app.core.origin import extract_publisher_from_html

    return extract_publisher_from_html(html)


def _prefer_main_html(html: str) -> str:
    """Drop chrome (nav/footer/cookie/paywall) and prefer <article>/<main> when present."""
    cleaned = html
    for tag in ("script", "style", "noscript", "nav", "footer", "header", "aside", "form"):
        cleaned = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}>",
            " ",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(
        r"<[^>]+(?:class|id)=['\"][^'\"]*(?:cookie|consent|paywall|subscribe|newsletter|sidebar|gdpr)[^'\"]*['\"][^>]*>.*?</[^>]+>",
        " ",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for tag in ("article", "main"):
        match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", cleaned, re.IGNORECASE | re.DOTALL)
        if match and len(re.sub(r"<[^>]+>", "", match.group(1)).strip()) >= MIN_CONTENT_CHARS:
            return match.group(1)
    return cleaned


def enrich_article(
    title: str,
    url: str,
    content: str,
    image_url: Optional[str] = None,
    fetch_fn: Optional[Callable] = None,
    fetch_publisher: bool = False,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Return (content, image_url, publisher_name).

    publisher_name is og:site_name / JSON-LD publisher when the page is fetched.
    It is never inferred from the URL host.
    """
    from app.core.parser import sanitize_html
    from app.core.urls import sanitize_http_url

    body = (content or "").strip()
    fallback = compose_feed_text(title, body)
    image = sanitize_http_url(image_url, keep_query=True) if image_url else ""

    if len(body) >= MIN_CONTENT_CHARS and not fetch_publisher:
        return fallback, image or None, None

    if len(body) >= MIN_CONTENT_CHARS and fetch_publisher:
        publisher = extract_publisher_name(body) or None
        if publisher or not fetch_fn or not url:
            return fallback, image or None, publisher

    if not fetch_fn or not url:
        return fallback, image or None, None

    try:
        response = fetch_fn(url, timeout=8)
        raw = getattr(response, "content", None)
        if raw is None:
            text = getattr(response, "text", "") or ""
            raw = text.encode("utf-8", errors="replace")
        if not isinstance(raw, (bytes, bytearray)):
            raw = str(raw).encode("utf-8", errors="replace")
        html = bytes(raw[:MAX_HTML_BYTES]).decode("utf-8", errors="replace")
        extracted = sanitize_html(_prefer_main_html(html))
        if len(body) >= MIN_CONTENT_CHARS:
            composed = fallback
        elif len(extracted) >= MIN_CONTENT_CHARS:
            composed = extracted[:MAX_CONTENT_CHARS]
        else:
            composed = compose_feed_text(title, extracted)
        if not image:
            image = extract_og_image(html)
        publisher = extract_publisher_name(html) or None
        return composed, image or None, publisher
    except Exception as exc:
        logger.info("Article body enrichment failed for %s: %s", url, exc)
        return fallback, image or None, None
