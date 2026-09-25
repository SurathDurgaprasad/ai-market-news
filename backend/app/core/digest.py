"""
Newsletter digests: one URL, several unrelated stories.

MIT Technology Review's "The Download" opens with a lead story, then lists
other outlets' stories under "The must-reads". The classifier and the
summarizer each read the whole page and chose their own "main" story, so a
card got the lead story's headline and the must-reads' entities (smart
glasses in India, but ShinyHunters and the FBI).

Both LLM calls now read the same lead segment: the digest text up to its
first link-roundup section. Ordinary articles are returned unchanged.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

# Self-description a digest opens with ("This is today's edition of The Download").
_DIGEST_OPENING = re.compile(
    r"\b(?:this is (?:today|this week|this morning)['’]s edition of|"
    r"our (?:weekday|daily|weekly) newsletter)\b",
    re.IGNORECASE,
)
_DIGEST_TITLE = re.compile(r"^\s*the download\s*:", re.IGNORECASE)

# Where a digest stops telling its own story and starts listing others'.
_ROUNDUP_SECTION = re.compile(
    r"\b(?:the must-reads|quote of the day|one more thing|we can still have nice things|"
    r"in other news|what else we(?:['’]re| are) reading|elsewhere on the web)\b",
    re.IGNORECASE,
)

# Only the opening is checked for the self-description.
_OPENING_WINDOW = 400
# A lead segment shorter than this is not enough to classify; keep the page.
_MIN_LEAD_CHARS = 300


def is_digest(title: Optional[str], content: Optional[str]) -> bool:
    text = content or ""
    return bool(_DIGEST_TITLE.search(title or "") or _DIGEST_OPENING.search(text[:_OPENING_WINDOW]))


def lead_segment(title: Optional[str], content: Optional[str]) -> str:
    """The digest's own lead story(ies), without the link roundup. Unchanged for ordinary articles."""
    text = content or ""
    if not is_digest(title, text):
        return text
    cut = _ROUNDUP_SECTION.search(text, _MIN_LEAD_CHARS)
    if cut is None:
        return text
    return text[: cut.start()].rstrip()


def entities_named_in(entities: Iterable[str], text: str) -> list[str]:
    """Entities that the chosen story actually names (case-insensitive, whole words)."""
    haystack = f" {re.sub(r'[^a-z0-9]+', ' ', (text or '').lower())} "
    kept: list[str] = []
    for entity in entities or []:
        if not isinstance(entity, str):
            continue
        needle = re.sub(r"[^a-z0-9]+", " ", entity.lower()).strip()
        if needle and f" {needle} " in haystack and entity not in kept:
            kept.append(entity)
    return kept
