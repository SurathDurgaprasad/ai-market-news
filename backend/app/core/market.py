"""
Market overview derived from canonical events already in the database.

Counts are events, not article copies. One publisher repeating a story does
not create a trend. No scores are shown to readers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

NOW_WINDOW = timedelta(hours=18)

# One event lands in at most one market category.
_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Robotics", re.compile(r"\brobots?\b|\brobotics\b", re.I)),
    ("Coding", re.compile(r"\b(coding|code generation|copilot|software engineering agent)\b", re.I)),
    ("Agents", re.compile(r"\bagents?\b", re.I)),
    ("Multimodal", re.compile(r"\b(multimodal|text-to-image|text-to-video|speech model|voice model)\b", re.I)),
    ("Open Source", re.compile(r"\b(open[- ]source|open[- ]weight)\b", re.I)),
    ("Infrastructure", re.compile(r"\b(inference cluster|data center|datacenter|gpu cluster)\b", re.I)),
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
    kind = (event.event_kind or "other").strip().lower()
    if kind == "security_incident":
        return "Security"
    text = " ".join([event.headline or "", event.summary or "", " ".join(event.entities)])
    for label, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return label
    return _KIND_CATEGORY.get(kind)


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
    sources = len({name for name in event.source_names if name}) or (1 if event.primary_source_name else 0)
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


def _distinct_sources(events: list[MarketEvent]) -> int:
    names = {name for event in events for name in event.source_names if name}
    if names:
        return len(names)
    return len({event.primary_source_name for event in events if event.primary_source_name})


def build_market_overview(events: list[MarketEvent], now: Optional[datetime] = None) -> dict:
    """
    Current-week overview.

    Happening now: today, plus the previous 18 hours when today is thin.
    Trending: a category with at least two events from two publishers, and
    at least one of those events inside the now window.
    Biggest: high-importance events not already shown in happening now.
    Pulse and players: counts of distinct canonical events.
    """
    moment = _utc(now or datetime.now(timezone.utc))
    today = moment.date()
    recent_cutoff = moment - NOW_WINDOW
    prepared = [event for event in events if event.occurred_at is not None]
    prepared.sort(key=lambda event: _utc(event.occurred_at), reverse=True)

    def on_day(event: MarketEvent, day) -> bool:
        return _utc(event.occurred_at).date() == day

    def is_recent(event: MarketEvent) -> bool:
        return _utc(event.occurred_at) >= recent_cutoff

    now_pool = [event for event in prepared if on_day(event, today) or is_recent(event)]
    now_pool.sort(key=lambda event: _utc(event.occurred_at), reverse=True)
    now_pool.sort(key=lambda event: event.importance, reverse=True)
    qualified = [event for event in now_pool if event.importance >= 50]
    happening = (qualified if len(qualified) >= 3 else now_pool)[:6]
    happening_ids = {event.id for event in happening}

    biggest_pool = [
        event for event in prepared
        if event.id not in happening_ids and event.importance >= 70
    ]
    biggest_pool.sort(key=lambda event: _utc(event.occurred_at), reverse=True)
    biggest_pool.sort(key=lambda event: event.importance, reverse=True)
    biggest = []
    seen_orgs: set[str] = set()
    for event in biggest_pool:
        org = _display_organization(event) or event.id
        if org in seen_orgs:
            continue
        seen_orgs.add(org)
        biggest.append(event)
        if len(biggest) == 4:
            break

    by_category: dict[str, list[MarketEvent]] = {}
    for event in prepared:
        category = market_category(event)
        if not category:
            continue
        by_category.setdefault(category, []).append(event)

    pulse = []
    trending = []
    for label, group in sorted(by_category.items(), key=lambda item: (-len(item[1]), item[0])):
        today_count = sum(1 for event in group if on_day(event, today))
        week_count = len(group)
        pulse.append({"label": label, "today": today_count, "week": week_count})
        recent_group = [event for event in group if is_recent(event) or on_day(event, today)]
        if week_count >= 2 and recent_group and _distinct_sources(group) >= 2:
            trending.append({
                "label": label,
                "today": today_count,
                "week": week_count,
            })
    trending.sort(key=lambda item: (-item["today"], -item["week"], item["label"]))
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
        players.append({
            "slug": slug,
            "name": name,
            "today": sum(1 for event in group if on_day(event, today)),
            "week": len(group),
            "latest_headline": latest.headline,
            "latest_event_id": latest.id,
            "event_ids": [event.id for event in sorted(group, key=lambda item: _utc(item.occurred_at), reverse=True)],
        })
    players.sort(key=lambda item: (-item["week"], -item["today"], item["name"]))

    return {
        "as_of": moment.isoformat(),
        "happening_now": [_card(event) for event in happening],
        "trending": trending,
        "biggest": [_card(event) for event in biggest],
        "pulse": pulse,
        "players": players[:8],
    }
