"""
Why an event does not currently carry a stored primary source.

PRIMARY_SOURCE_NOT_DISCOVERED means no official URL is in the stored
evidence. It does not mean a primary document was confirmed not to exist.
There is no confirmed-absent state.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Provenance(str, Enum):
    STORED_PRIMARY = "STORED_PRIMARY"
    PRIMARY_SOURCE_NOT_DISCOVERED = "PRIMARY_SOURCE_NOT_DISCOVERED"
    LEGITIMATELY_SECONDARY = "LEGITIMATELY_SECONDARY"
    FEED_MISSING = "FEED_MISSING"
    DISCOVERED_BUT_NOT_STORED = "DISCOVERED_BUT_NOT_STORED"
    PRIMARY_SOURCE_BLOCKED = "PRIMARY_SOURCE_BLOCKED"
    PRIMARY_SOURCE_RESOLUTION_FAILED = "PRIMARY_SOURCE_RESOLUTION_FAILED"


@dataclass
class ProvenanceFacts:
    """Stored evidence only. Missing fields are unknown, not confirmed empty."""

    best_tier: str = ""
    article_host: str = ""
    ingest_is_aggregator: bool = False
    publisher_name: Optional[str] = None
    official_source_name: Optional[str] = None
    official_host_matches_primary: bool = False
    feed_status: str = ""
    legitimately_secondary: bool = False


def classify_provenance(facts: ProvenanceFacts) -> Provenance:
    """
    Classify stored provenance.

    feed_status is the registered feed's observed result: "ok", "404",
    "not_feed", "403", or "" when this event is not tied to that feed.
    A 403 is blocked access, not evidence that no official source exists.
    """
    tier = (facts.best_tier or "").lower()
    publisher = (facts.publisher_name or "").strip()
    official = (facts.official_source_name or "").strip()
    if tier == "primary" or (official and facts.official_host_matches_primary):
        return Provenance.STORED_PRIMARY
    if official and tier == "research":
        return Provenance.STORED_PRIMARY

    host = (facts.article_host or "").lower().removeprefix("www.")
    discovered_url = bool(host) and facts.ingest_is_aggregator
    if discovered_url and not official:
        if publisher:
            return Provenance.PRIMARY_SOURCE_RESOLUTION_FAILED
        return Provenance.DISCOVERED_BUT_NOT_STORED

    status = (facts.feed_status or "").lower()
    if status in {"403", "blocked"}:
        return Provenance.PRIMARY_SOURCE_BLOCKED
    if status in {"404", "not_feed"}:
        return Provenance.FEED_MISSING
    if facts.legitimately_secondary:
        return Provenance.LEGITIMATELY_SECONDARY
    return Provenance.PRIMARY_SOURCE_NOT_DISCOVERED
