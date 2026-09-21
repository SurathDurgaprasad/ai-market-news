"""Normalize and rank entities. Does not invent names."""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

_GENERIC = {
    "ai", "ml", "llm", "gpu", "cpu", "api", "sdk", "oss", "open source",
    "github", "blog", "paper", "model", "models", "release", "update",
    "fifo", "python", "javascript",
}


def _clean_one(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    text = text.strip(" \t,;|/")
    return text


def dedupe_entities(values: Optional[Iterable]) -> List[str]:
    """Case-insensitive dedupe, first spelling wins."""
    seen = set()
    out: List[str] = []
    for item in values or []:
        if not isinstance(item, str):
            continue
        cleaned = _clean_one(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen or key in _GENERIC:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def select_primary_entities(
    *,
    primary: Optional[Sequence] = None,
    mentioned: Optional[Sequence] = None,
    all_entities: Optional[Sequence] = None,
    headline: Optional[str] = None,
    summary: Optional[str] = None,
    limit: int = 6,
) -> Tuple[List[str], List[str]]:
    """
    Return (primary, mentioned).

    Preference order:
    1. explicit primary_entities from the classifier
    2. names that appear in the headline
    3. names that appear in the first summary sentence
    4. remaining unique names as mentioned
    """
    explicit_primary = dedupe_entities(primary)
    mentioned_clean = dedupe_entities(mentioned)
    pool = dedupe_entities(list(explicit_primary) + list(all_entities or []) + mentioned_clean)

    if explicit_primary and len(explicit_primary) <= limit:
        primary_out = explicit_primary
        primary_keys = {item.lower() for item in primary_out}
        mentioned_out = [item for item in pool if item.lower() not in primary_keys]
        return primary_out, mentioned_out

    head = (headline or "").lower()
    sum_text = (summary or "").split(".")[0].lower() if summary else ""
    ranked: List[str] = []
    rest: List[str] = []
    for item in pool:
        key = item.lower()
        if key and key in head:
            ranked.append(item)
        elif key and key in sum_text:
            ranked.append(item)
        else:
            rest.append(item)
    primary_out = (ranked + rest)[:limit]
    primary_keys = {item.lower() for item in primary_out}
    mentioned_out = [item for item in pool if item.lower() not in primary_keys][:24]
    return primary_out, mentioned_out
