"""
Presentation-boundary helpers for the intelligence feed.

These do not change event identity, grouping, or importance scoring.
They only shape what the API/UI may show.
"""
from __future__ import annotations

from typing import Iterable, List, Optional
from urllib.parse import urlparse

_WRAP_PAIRS = (
    ('"', '"'),
    ("'", "'"),
    ("\u201c", "\u201d"),  # “ ”
    ("\u2018", "\u2019"),  # ‘ ’
    ("\u00ab", "\u00bb"),  # « »
    ("\u201e", "\u201c"),  # „ “
)


def strip_wrapping_quotes(text: Optional[str]) -> str:
    """
    Remove wrapping quotation marks so the UI can always render “…” once.

    Does not strip apostrophes inside contractions (Don't, model's).
    Only paired wrapping quotes at both ends are removed, repeatedly.
    """
    cleaned = (text or "").strip()
    while len(cleaned) >= 2:
        matched = False
        for start, end in _WRAP_PAIRS:
            if cleaned.startswith(start) and cleaned.endswith(end) and len(cleaned) > len(start) + len(end):
                inner = cleaned[len(start) : -len(end)].strip()
                if inner:
                    cleaned = inner
                    matched = True
                    break
        if not matched:
            break
    return cleaned


def present_citations(citations: Optional[Iterable]) -> List[str]:
    presented: List[str] = []
    for item in citations or []:
        if not isinstance(item, str):
            continue
        cleaned = strip_wrapping_quotes(item)
        if cleaned:
            presented.append(cleaned)
    return presented


def classify_image_role(url: Optional[str]) -> str:
    """
    hero | source | none from URL evidence, not from the event's company name.

    Observed production corpus:
    - blogs.nvidia.com wp-content photos → photographic product/event imagery (hero)
    - opengraph.githubassets.com → GitHub page chrome (none)
    - huggingface.co/blog/assets thumbnails and cdn-uploads graphics → article graphics (source)
    Missing URL → none.
    Unknown hosts with an image URL default to source, not hero.
    """
    if not url or not str(url).strip():
        return "none"
    parsed = urlparse(str(url).strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if host.endswith("opengraph.githubassets.com"):
        return "none"
    if "github.com" in host and ("/opengraph" in path or path.endswith("/og.png")):
        return "none"
    if any(token in path for token in ("/favicon", "/logo.", "/logos/", "/sprite", "/icon-")):
        return "none"
    if host.endswith("blogs.nvidia.com"):
        return "hero"
    if host.endswith("nvidia.com") and "/wp-content/uploads/" in path:
        return "hero"
    return "source"
