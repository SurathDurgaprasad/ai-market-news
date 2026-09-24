"""
RSS/Atom feed parsing.

External feed payloads are untrusted. This module:
- never raises on malformed XML (returns whatever entries can be salvaged)
- isolates per-entry failures so one bad item cannot drop the feed
- sanitizes HTML
- validates image URLs (http/https only)
- caps feed size
- prefers published time, falls back to Atom updated time
- interprets feedparser struct_time as UTC
"""
from typing import Optional, List
import json
import re
import html
import calendar
import logging
from datetime import datetime, timezone
import feedparser

from app.core.urls import sanitize_http_url

logger = logging.getLogger(__name__)

# Protect the pipeline from pathological feeds (some aggregators dump 1000+ items).
MAX_FEED_ENTRIES = 100

class ArticleData:
    def __init__(self, title: str, url: str, content: str, published_at: Optional[datetime] = None, image_url: Optional[str] = None):
        self.title = title
        self.url = url
        self.content = content
        self.published_at = published_at
        self.image_url = image_url

_TAG_STOP = re.compile(r"""[>"']""")


def _strip_tags(text: str) -> str:
    """
    Replace markup with spaces, honouring quoted attribute values, in linear
    time. A quoted value may legally contain ">" (JSON props carrying
    "<p>...</p>"); ending the tag at the first ">" leaked the rest of the
    attribute into the article text. An unclosed quote falls back to the
    first ">" so hostile input cannot make this quadratic.
    """
    out: list[str] = []
    i, n = 0, len(text)
    unclosed_after = {'"': n + 1, "'": n + 1}  # a quote char known absent after this index
    while i < n:
        start = text.find("<", i)
        if start < 0:
            out.append(text[i:])
            break
        out.append(text[i:start])
        nxt = text[start + 1: start + 2]
        if not (nxt.isalpha() or nxt in ("/", "!", "?")):
            out.append("<")
            i = start + 1
            continue
        k, end = start + 1, -1
        while True:
            stop = _TAG_STOP.search(text, k)
            if stop is None:
                break
            char = stop.group(0)
            if char == ">":
                end = stop.start()
                break
            back = stop.start() - 1
            while back > start and text[back] in " \t\r\n":
                back -= 1
            if text[back] != "=":
                k = stop.start() + 1  # a stray apostrophe, not an attribute value
                continue
            close = -1 if stop.start() >= unclosed_after[char] else text.find(char, stop.start() + 1)
            if close < 0:
                unclosed_after[char] = min(unclosed_after[char], stop.start())
                break
            k = close + 1
        if end < 0:
            end = text.find(">", start)  # previous behaviour for malformed markup
            if end < 0:
                out.append(text[start:])
                break
        out.append(" ")
        i = end + 1
    return "".join(out)


def sanitize_html(html_str: str) -> str:
    if not html_str:
        return ""
    cleaned = re.sub(r'<script\b[^>]*>.*?</script>', '', html_str, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<style\b[^>]*>.*?</style>', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r'<!--.*?-->', '', cleaned, flags=re.DOTALL)
    # Quote-aware: a quoted attribute value may legally contain ">" (for
    # example JSON props carrying "<p>...</p>"). Ending the tag at the first
    # ">" leaked the rest of the attribute into the article text.
    cleaned = _strip_tags(cleaned)
    cleaned = html.unescape(cleaned)
    # Prevent XML breakout in LLM context and fake <system> tags
    cleaned = cleaned.replace('<', '＜').replace('>', '＞')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()


def _entry_url(entry) -> str:
    link = entry.get("link") or ""
    if isinstance(link, list):
        for item in link:
            if isinstance(item, dict) and item.get("href"):
                rel = item.get("rel")
                if rel in (None, "", "alternate"):
                    return item["href"]
        if link:
            first = link[0]
            if isinstance(first, dict):
                return first.get("href") or ""
            return str(first)
        return ""
    if isinstance(link, dict):
        return link.get("href") or ""
    return str(link)


def _entry_published(entry) -> Optional[datetime]:
    """
    Prefer RSS pubDate (published_parsed). Fall back to Atom updated.
    feedparser struct_time values are UTC; calendar.timegm preserves that.
    Invalid/missing dates return None rather than crashing the entry.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    except (OverflowError, ValueError, TypeError, OSError) as exc:
        logger.debug(f"Invalid feed date {parsed!r}: {exc}")
        return None


def _entry_image(entry, content_raw: str) -> Optional[str]:
    """
    Image preference:
    1. media:content
    2. media:thumbnail
    3. enclosure with image/* type
    4. link rel=enclosure image
    5. first absolute http(s) <img src> in HTML
    """
    candidates = []
    if entry.get("media_content"):
        for mc in entry.media_content:
            if mc.get("url"):
                candidates.append(mc.get("url"))
    if entry.get("media_thumbnail"):
        for th in entry.media_thumbnail:
            if th.get("url"):
                candidates.append(th.get("url"))
    if entry.get("enclosures"):
        for enc in entry.enclosures:
            if str(enc.get("type") or "").startswith("image/") and enc.get("href"):
                candidates.append(enc.get("href"))
    if entry.get("links"):
        for link in entry.links:
            if str(link.get("type") or "").startswith("image/") and link.get("href"):
                candidates.append(link.get("href"))
            elif link.get("rel") == "enclosure" and str(link.get("type") or "").startswith("image/"):
                candidates.append(link.get("href"))
    if content_raw:
        for match in re.finditer(
            r'<img[^>]+src=["\']([^"\']+)["\']',
            content_raw,
            re.IGNORECASE,
        ):
            candidates.append(match.group(1))

    for raw in candidates:
        safe = sanitize_http_url(raw, keep_query=True)
        if safe:
            return safe
    return None


def parse_rss_feed(payload: str) -> List[ArticleData]:
    """
    Parse an RSS or Atom payload into ArticleData records.

    Never raises on malformed XML. Per-entry errors are logged and skipped.
    Duplicate URLs inside a single feed are dropped (first occurrence wins).
    """
    if not payload:
        return []

    # Strip UTF-8 BOM if present — some feeds include it and confuse parsers.
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    if payload.startswith("\ufeff"):
        payload = payload.lstrip("\ufeff")

    try:
        feed = feedparser.parse(payload)
    except Exception as exc:
        logger.error(f"feedparser crashed on payload: {exc}")
        return []

    articles: List[ArticleData] = []
    seen_urls: set[str] = set()

    for entry in feed.entries[:MAX_FEED_ENTRIES]:
        try:
            title = sanitize_html(entry.get("title") or "")
            url = sanitize_http_url(_entry_url(entry), keep_query=False)
            if not title or not url:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)

            content_raw = ""
            if entry.get("content") and len(entry.content) > 0:
                content_raw = entry.content[0].value or ""
            else:
                content_raw = entry.get("summary") or entry.get("description") or ""

            content = sanitize_html(content_raw)
            published = _entry_published(entry)
            image_url = _entry_image(entry, content_raw)

            articles.append(ArticleData(
                title=title,
                url=url,
                content=content,
                published_at=published,
                image_url=image_url,
            ))
        except Exception as exc:
            logger.warning(f"Skipping malformed feed entry: {exc}")
            continue

    return articles


_FEED_ROOT_RE = re.compile(r"<rss\b|<feed\b|<rdf:rdf\b", re.IGNORECASE)


def looks_like_feed(payload: str) -> bool:
    """
    True if the payload has the structural shape of an RSS/Atom/RDF feed,
    independent of whether it parsed to any entries.

    Exists to distinguish "this source's feed genuinely has nothing new
    right now" from "this source stopped serving a feed at all" — e.g. a
    feed URL that starts returning an HTML 404/moved-notice page after a
    CMS migration. feedparser's own `bozo` flag does NOT catch that case:
    an HTML page is "well-formed enough" XML-adjacent content that `bozo`
    stays False and `entries` is simply empty, identical to a truly empty
    but well-formed feed. See docs/RED_TEAM_REPORT.md INGEST-SILENT-01.

    Deliberately simple (a root-tag substring check, not a full parse) —
    real feeds declare their root element within the first few KB, so
    only that prefix is scanned, bounding the cost even against a
    maliciously large non-feed body.
    """
    if not payload:
        return False
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    return bool(_FEED_ROOT_RE.search(payload[:4096]))


def extract_feed_next_url(payload: str) -> Optional[str]:
    """
    Return a sanitized http(s) URL if the feed advertises Atom/RSS pagination.

    Current configured sources publish a recent window (HN 30 items, blogs
    typically 10–20). With 10–60 minute polling, following page=2 is not
    required and can pull stale duplicates. We detect and log, we do not follow.
    """
    if not payload:
        return None
    try:
        feed = feedparser.parse(payload)
    except Exception:
        return None
    links = []
    if getattr(feed, "feed", None):
        links.extend(feed.feed.get("links") or [])
    for link in links:
        if not isinstance(link, dict):
            continue
        if str(link.get("rel") or "").lower() != "next":
            continue
        href = link.get("href")
        safe = sanitize_http_url(href, keep_query=True) if href else ""
        if safe:
            return safe
    return None

def parse_mock_source(payload: str) -> Optional[ArticleData]:
    """
    Parses a mock JSON payload (used in existing tests).
    """
    try:
        data = json.loads(payload)

        content = data.get("content", "")
        title = data.get("title", "")

        title = sanitize_html(title)
        content = sanitize_html(content)
        url = sanitize_http_url(data.get("url", ""), keep_query=False)
        published = data.get("published_at")
        image_url = sanitize_http_url(data.get("image_url"), keep_query=True) or None

        if published:
            try:
                published = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except ValueError:
                published = None

        if not title or not url:
            return None

        return ArticleData(title=title, url=url, content=content, published_at=published, image_url=image_url)
    except json.JSONDecodeError:
        return None
