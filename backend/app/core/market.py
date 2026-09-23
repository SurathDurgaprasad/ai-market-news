"""
Market overview derived from canonical events already in the database.

Counts are events, not article copies. One publisher repeating a story does
not create a trend. No numeric rank is shown to readers.

Time basis, applied consistently:
- Stored timestamps are UTC and must be displayed as UTC.
- This week is the ISO week starting Monday 00:00 UTC, same as the feed.
- Now is the last 36 hours, not "the UTC calendar date is today".
- A 24-hour count is omitted when it is zero, so a sparse morning does not
  read as an empty market. The event's own timestamp is never rewritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

NOW_WINDOW = timedelta(hours=36)
DAY_WINDOW = timedelta(hours=24)

# One event lands in at most one market category.
_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Robotics", re.compile(r"\brobots?\b|\brobotics\b", re.I)),
    ("Coding", re.compile(r"\b(coding|code generation|copilot|software engineering agent)\b", re.I)),
    ("Agents", re.compile(r"\bagents?\b", re.I)),
    ("Multimodal", re.compile(r"\b(multimodal|text-to-image|text-to-video|speech model|voice model)\b", re.I)),
    ("Open Source", re.compile(r"\b(open[- ]source|open[- ]weight|gguf|llama\.cpp)\b", re.I)),
    ("Infrastructure", re.compile(r"\b(inference cluster|data center|datacenter|gpu cluster|sagemaker)\b", re.I)),
)

_HEADLINE_SECURITY = re.compile(r"\b(malware|ransomware|vulnerability|cyberattack)\b", re.I)
_HEADLINE_MODEL = re.compile(r"\b(large language model|foundation model|llm|gpt-\d)\b", re.I)
_HEADLINE_RESEARCH = re.compile(r"\bresearch\b", re.I)
_HEADLINE_ASSISTANT = re.compile(r"\b(ai assistant|ai bots?|chatbots?|agentforce)\b", re.I)
_SUBSTANCE = {
    "model_release": 3,
    "model_family": 3,
    "hardware_platform": 3,
    "security_incident": 3,
    "research": 3,
    "open_source_release": 2,
    "benchmark": 2,
    "funding": 2,
    "acquisition": 2,
    "capability": 1,
    "partnership": 1,
    "tool_update": 0,
    "migration": 0,
    "maintenance": 0,
    "other": 0,
}
_CATEGORY_SUBSTANCE = {
    "Models": 3,
    "Hardware": 3,
    "Security": 3,
    "Research": 3,
    "Robotics": 2,
    "Open Source": 2,
    "Infrastructure": 2,
    "Agents": 2,
    "Multimodal": 2,
    "Coding": 2,
    "Funding": 1,
    "Partnerships": 1,
}
_HEADLINE_HARDWARE = re.compile(r"\bhardware\b", re.I)
_HEADLINE_ENDPOINT = re.compile(r"\b(endpoint|sagemaker)\b", re.I)
_HEADLINE_CODING = re.compile(r"\bide\b", re.I)
_ROUNDUP = re.compile(r"\b(roundup|companies lead|survey of)\b", re.I)
_CUSTOMER_DEPLOYMENT = re.compile(
    r"\b(implements|implementation of|now operates on|launches\b.{0,80}\bsolution)\b",
    re.I,
)

_KIND_CATEGORY = {
    "security_incident": "Security",
    "funding": "Funding",
    "acquisition": "Partnerships",
    "partnership": "Partnerships",
    "open_source_release": "Open Source",
    "hardware_platform": "Hardware",
    "research": "Research",
    "benchmark": "Research",
    "model_release": "Models",
    "model_family": "Models",
}

# Identity aliases only. Activity still has to come from stored events.
PLAYERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("openai", "OpenAI", ("openai", "chatgpt")),
    ("anthropic", "Anthropic", ("anthropic", "claude")),
    ("google", "Google / DeepMind", ("google", "deepmind", "gemini")),
    ("microsoft", "Microsoft", ("microsoft",)),
    ("meta", "Meta", ("meta",)),
    ("nvidia", "NVIDIA", ("nvidia",)),
    ("xai", "xAI", ("xai", "grok")),
    ("amazon", "Amazon", ("amazon", "aws", "bedrock", "sagemaker")),
    ("alibaba", "Alibaba / Qwen", ("alibaba", "qwen")),
    ("mistral", "Mistral", ("mistral",)),
    ("huggingface", "Hugging Face", ("hugging face", "huggingface")),
)

_PLAYER_BY_SLUG = {slug: (name, aliases) for slug, name, aliases in PLAYERS}


@dataclass
class MarketEvent:
    id: str
    headline: str
    summary: str
    importance: int
    occurred_at: datetime
    entities: list[str] = field(default_factory=list)
    event_kind: str = "other"
    source_names: list[str] = field(default_factory=list)
    source_tiers: list[str] = field(default_factory=list)
    organization_name: str = ""
    primary_source_name: str = ""


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _alias_in(text: str, alias: str) -> bool:
    hay = f" {_norm(text)} "
    needle = f" {_norm(alias)} "
    return needle.strip() != "" and needle in hay


def market_category(event: MarketEvent) -> Optional[str]:
    """
    One primary category. Keyword evidence wins over a generic kind.
    A headline can fill a missing kind. Customer deployments and policy
    notes stay uncategorized when the headline does not name a category.
    """
    kind = (event.event_kind or "other").strip().lower()
    headline = event.headline or ""
    if kind == "security_incident" or _HEADLINE_SECURITY.search(headline):
        return "Security"
    text = " ".join([headline, event.summary or "", " ".join(event.entities)])
    for label, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return label
    if _HEADLINE_CODING.search(headline):
        return "Coding"
    mapped = _KIND_CATEGORY.get(kind)
    if mapped:
        return mapped
    if _HEADLINE_MODEL.search(headline):
        return "Models"
    if _HEADLINE_ENDPOINT.search(headline):
        return "Infrastructure"
    if _HEADLINE_HARDWARE.search(headline):
        return "Hardware"
    if _HEADLINE_RESEARCH.search(headline):
        return "Research"
    if _HEADLINE_ASSISTANT.search(headline):
        return "Agents"
    if re.search(r"\bbedrock\b", headline, re.I) and kind in {"capability", "tool_update", "other"}:
        return "Infrastructure"
    return None


def _substance(event: MarketEvent) -> int:
    kind = (event.event_kind or "other").strip().lower()
    category = market_category(event) or ""
    return max(_SUBSTANCE.get(kind, 0), _CATEGORY_SUBSTANCE.get(category, 0))


def is_significant_development(event: MarketEvent) -> bool:
    """Importance band, excluding customer deployments and roundups."""
    if event.importance < 70:
        return False
    if is_roundup(event) or _is_customer_deployment(event):
        return False
    return True


def importance_label(score: int) -> str:
    if score >= 90:
        return "Major"
    if score >= 70:
        return "Significant"
    if score >= 50:
        return "Notable"
    return "Minor"


def source_availability(event: MarketEvent) -> str:
    tiers = {(tier or "").lower() for tier in event.source_tiers}
    if "primary" in tiers:
        return "Official source"
    if "research" in tiers or (event.event_kind or "") == "research":
        return "Research"
    if "secondary" in tiers:
        return "Supporting coverage"
    if "community" in tiers:
        return "Discussion"
    return ""


def _players_in(parts: list[str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for slug, name, aliases in PLAYERS:
        if any(_alias_in(part, alias) for part in parts for alias in aliases):
            found.append((slug, name))
    return found


def matching_players(event: MarketEvent) -> list[tuple[str, str]]:
    """
    Attribute an event to an organization when that organization published it,
    or when the headline and the extracted entities both name it.

    A headline that names three or more of these organizations is a roundup,
    not each organization's development.
    """
    published = _players_in([event.organization_name, event.primary_source_name])
    named: list[tuple[str, str]] = []
    for slug, name, aliases in PLAYERS:
        in_entities = any(_alias_in(entity, alias) for entity in event.entities for alias in aliases)
        in_headline = any(_alias_in(event.headline or "", alias) for alias in aliases)
        if in_entities and in_headline:
            named.append((slug, name))
    if len(named) >= 3:
        named = []
    merged: list[tuple[str, str]] = []
    seen: set[str] = set()
    for slug, name in published + named:
        if slug in seen:
            continue
        seen.add(slug)
        merged.append((slug, name))
    return merged


def event_matches_player(event: MarketEvent, slug: str) -> bool:
    return any(found == slug for found, _name in matching_players(event))


def _display_organization(event: MarketEvent) -> str:
    published = _players_in([event.organization_name, event.primary_source_name])
    if published:
        return published[0][1]
    if len(_players_in(list(event.entities))) >= 3:
        return event.primary_source_name or event.organization_name or ""
    players = matching_players(event)
    if players:
        return players[0][1]
    for entity in event.entities:
        cleaned = entity.strip()
        if cleaned:
            return cleaned
    return event.organization_name or event.primary_source_name or ""


def _card(event: MarketEvent) -> dict:
    category = market_category(event)
    sources = _source_count(event)
    return {
        "id": event.id,
        "headline": event.headline,
        "summary": (event.summary or "").strip(),
        "organization": _display_organization(event),
        "category": category or "",
        "event_time": _utc(event.occurred_at).isoformat(),
        "importance_score": event.importance,
        "importance_label": importance_label(event.importance),
        "source_count": sources,
        "source_label": source_availability(event),
    }


def _best_tier(event: MarketEvent) -> str:
    tiers = {(tier or "").lower() for tier in event.source_tiers}
    if "primary" in tiers:
        return "primary"
    if "research" in tiers or (event.event_kind or "") == "research":
        return "research"
    if "secondary" in tiers:
        return "secondary"
    if "community" in tiers:
        return "community"
    return ""


def _tier_rank(event: MarketEvent) -> int:
    return {"primary": 3, "research": 2, "secondary": 1, "community": 0}.get(_best_tier(event), 0)


def is_roundup(event: MarketEvent) -> bool:
    if len(_players_in(list(event.entities))) >= 3:
        return True
    return bool(_ROUNDUP.search(event.headline or ""))


def is_discussion(event: MarketEvent) -> bool:
    return _best_tier(event) == "community"


def _is_customer_deployment(event: MarketEvent) -> bool:
    return bool(_CUSTOMER_DEPLOYMENT.search(event.headline or ""))


def _source_count(event: MarketEvent) -> int:
    names = {name for name in event.source_names if name}
    if names:
        return len(names)
    return 1 if event.primary_source_name else 0


def _age_hours(event: MarketEvent, moment: datetime) -> float:
    return (moment - _utc(event.occurred_at)).total_seconds() / 3600


def _within(event: MarketEvent, moment: datetime, window: timedelta) -> bool:
    age = _age_hours(event, moment)
    return 0 <= age <= window.total_seconds() / 3600


def _quality_key(event: MarketEvent, moment: datetime) -> tuple:
    """
    Higher is a better overview candidate. Not shown to readers.

    Direct announcements and research outrank discussion and roundups.
    Importance is a tie-break after source quality, not the only sort.
    """
    age = _age_hours(event, moment)
    if age <= 24:
        recency = 2
    elif age <= 36:
        recency = 1
    else:
        recency = 0
    direct = 0 if is_roundup(event) or is_discussion(event) else 1
    not_customer_story = 0 if _is_customer_deployment(event) else 1
    return (
        direct,
        not_customer_story,
        _substance(event),
        1 if event.importance >= 90 else 0,
        1 if event.importance >= 70 else 0,
        _tier_rank(event),
        min(_source_count(event), 3),
        recency,
        event.importance,
        _utc(event.occurred_at),
    )


def _take_diverse(events: list[MarketEvent], limit: int, per_org: int) -> list[MarketEvent]:
    chosen: list[MarketEvent] = []
    seen: dict[str, int] = {}
    for event in events:
        org = _display_organization(event) or event.id
        if seen.get(org, 0) >= per_org:
            continue
        seen[org] = seen.get(org, 0) + 1
        chosen.append(event)
        if len(chosen) == limit:
            break
    return chosen


def _distinct_sources(events: list[MarketEvent]) -> int:
    names = {name for event in events for name in event.source_names if name}
    if names:
        return len(names)
    return len({event.primary_source_name for event in events if event.primary_source_name})


def _activity_label(recent: int, sources: int) -> str:
    """Only when the recent window itself holds a measurable cluster."""
    if recent >= 3 and sources >= 2:
        return "High"
    return ""


def build_market_overview(events: list[MarketEvent], now: Optional[datetime] = None) -> dict:
    """
    Current-week overview.

    Happening now: meaningful developments in the last 36 hours. Official
    and research items outrank discussion and roundups when any exist.
    Trending: a category with at least two events from two publishers and
    at least one event in that 36-hour window.
    Biggest: high-importance direct developments elsewhere in the week.
    """
    moment = _utc(now or datetime.now(timezone.utc))
    prepared = [event for event in events if event.occurred_at is not None]
    prepared.sort(key=lambda event: _utc(event.occurred_at), reverse=True)

    def in_now(event: MarketEvent) -> bool:
        return _within(event, moment, NOW_WINDOW)

    def in_day(event: MarketEvent) -> bool:
        return _within(event, moment, DAY_WINDOW)

    window = [event for event in prepared if in_now(event)]
    direct = [
        event for event in window
        if not is_discussion(event) and not is_roundup(event) and event.importance >= 50
    ]
    now_pool = direct if direct else [event for event in window if event.importance >= 50] or window
    now_pool.sort(key=lambda event: _quality_key(event, moment), reverse=True)
    happening = _take_diverse(now_pool, limit=6, per_org=2)
    happening_ids = {event.id for event in happening}

    biggest_pool = [
        event for event in prepared
        if event.id not in happening_ids and event.importance >= 70
    ]
    direct_big = [event for event in biggest_pool if not is_discussion(event) and not is_roundup(event)]
    if direct_big:
        biggest_pool = direct_big
    biggest_pool.sort(key=lambda event: _quality_key(event, moment), reverse=True)
    biggest = _take_diverse(biggest_pool, limit=4, per_org=1)

    by_category: dict[str, list[MarketEvent]] = {}
    for event in prepared:
        category = market_category(event)
        if not category:
            continue
        by_category.setdefault(category, []).append(event)

    pulse = []
    trending = []
    for label, group in sorted(by_category.items(), key=lambda item: (-len(item[1]), item[0])):
        week_count = len(group)
        day_count = sum(1 for event in group if in_day(event))
        pulse_row = {"label": label, "week": week_count}
        if day_count:
            pulse_row["recent"] = day_count
        pulse.append(pulse_row)
        recent_count = sum(1 for event in group if in_now(event))
        sources = _distinct_sources(group)
        if week_count >= 2 and recent_count >= 1 and sources >= 2:
            trending.append({
                "label": label,
                "week": week_count,
                "sources": sources,
                "recent": recent_count,
                "activity": _activity_label(recent_count, sources),
            })
    trending.sort(key=lambda item: (-item["recent"], -item["week"], -item["sources"], item["label"]))
    trending = trending[:4]

    player_groups: dict[str, list[MarketEvent]] = {}
    for event in prepared:
        for slug, _name in matching_players(event):
            player_groups.setdefault(slug, []).append(event)

    players = []
    for slug, name, _aliases in PLAYERS:
        group = player_groups.get(slug) or []
        if not group:
            continue
        latest = max(group, key=lambda event: _utc(event.occurred_at))
        significant = sum(1 for event in group if is_significant_development(event))
        players.append({
            "slug": slug,
            "name": name,
            "week": len(group),
            "significant": significant,
            "sources": _distinct_sources(group),
            "latest_headline": latest.headline,
            "latest_event_id": latest.id,
            "latest_time": _utc(latest.occurred_at).isoformat(),
            "event_ids": [event.id for event in sorted(group, key=lambda item: _utc(item.occurred_at), reverse=True)],
        })
    players.sort(key=lambda item: (-item["significant"], -item["sources"], -item["week"], item["name"]))

    return {
        "as_of": moment.isoformat(),
        "happening_now": [_card(event) for event in happening],
        "trending": trending,
        "biggest": [_card(event) for event in biggest],
        "pulse": pulse,
        "players": players[:8],
    }
