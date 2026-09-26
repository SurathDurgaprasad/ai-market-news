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
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.deduplication import classify_headline_relationship
from app.core.providers.llm import EventRelationship

NOW_WINDOW = timedelta(hours=36)
DAY_WINDOW = timedelta(hours=24)

# One event lands in at most one market category.
_CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Robotics", re.compile(r"\brobots?\b|\brobotics\b", re.I)),
    ("Coding", re.compile(r"\b(coding|code generation|copilot|software engineering agent)\b", re.I)),
    ("Agents", re.compile(r"\bagents?\b", re.I)),
    ("Multimodal", re.compile(r"\b(multimodal|text-to-image|text-to-video|speech model|voice model)\b", re.I)),
    ("Open Source", re.compile(r"\b(open[- ]source|open[- ]weights?|open models?|gguf|llama\.cpp)\b", re.I)),
    ("Infrastructure", re.compile(r"\b(inference cluster|data center|datacenter|gpu cluster|sagemaker)\b", re.I)),
)

# Named products whose market area is unambiguous. Checked only for generic
# kinds, after every rule above, so a stored specific kind still wins.
_NAMED_AREA_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Robotics", re.compile(r"\b(reachy|humanoids?)\b", re.I)),
    ("Research", re.compile(r"\b(alphafold|alphaevolve|theorems?)\b", re.I)),
    ("Coding", re.compile(r"\bcodex\b", re.I)),
    ("Multimodal", re.compile(
        r"\b(images \d|image generation|video generation|audio model|4d reconstruction|live translate)\b", re.I)),
    ("Models", re.compile(
        r"\b(gemini|gemma|gpt|claude|llama|lyria|veo|pixtral|qwen|grok)[- ]?\d+(\.\d+)?\b"
        r"|\bnew (?:\w+ )?models\b", re.I)),
    ("Agents", re.compile(r"\b(langchain|langsmith|langgraph|deepagents|agentcore|mcp)\b", re.I)),
    ("Infrastructure", re.compile(
        r"\b(vllm|gpus?|inference|kernels|object storage|distributed storage|batch api)\b", re.I)),
)
# Headlines use typographic hyphens ("GPT\u20116"); rules are written with "-".
_HYPHENS = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2212]")

_HEADLINE_SECURITY = re.compile(r"\b(malware|ransomware|vulnerability|cyberattack)\b", re.I)
# A stored security_incident kind must be backed by security language in the
# headline or summary. A policy declaration or a hype critique is not an
# incident just because the classifier chose that kind.
_SECURITY_TERMS = re.compile(
    r"\b(secur\w*|vulnerab\w*|breach\w*|attack\w*|malware|ransomware|exploit\w*|"
    r"hack\w*|leak\w*|jailbreak\w*|fraud\w*|phishing|scam\w*|cyber\w*|cve-\d+|"
    r"compromis\w*|backdoor\w*|spyware|intrusion\w*|stolen|theft)\b",
    re.I,
)
_HEADLINE_POLICY = re.compile(
    r"\b(regulat\w*|legislat\w*|laws?|policy|policies|oversight|governance|"
    r"executive order|antitrust|lawsuits?|sues|sued|court|ruling|senate|congress|"
    r"parliament|standards)\b",
    re.I,
)
_HEADLINE_MODEL = re.compile(r"\b(large language model|foundation model|llm|gpt-\d)\b", re.I)
_HEADLINE_RESEARCH = re.compile(r"\bresearch\b", re.I)
# A personnel move names a person, not a market area: "Resigns from Google to
# focus on AI research" is not Research. Only the classifier may categorize it.
_HEADLINE_PERSONNEL = re.compile(
    r"\b(resign\w*|steps? down|stepping down|departs|departure|exits|poach\w*|hires|hired|appoint\w*|"
    r"named (?:as )?(?:its )?(?:new )?(?:ceo|cto|cfo|chief|head|president))\b",
    re.I,
)
_HEADLINE_ASSISTANT = re.compile(r"\b(ai assistant|ai bots?|chatbots?)\b", re.I)
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
    "Policy": 2,
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
# "Retailer automates X using Amazon Bedrock": a customer story on a
# vendor blog. The vendor naming itself as the subject is not matched.
_CUSTOMER_ON_PLATFORM = re.compile(
    r"^(?!\s*(?:amazon|aws|microsoft|azure|google)\b).*"
    r"\b(automates?|enhances?|improves?|streamlines?|transforms?|modernizes?|"
    r"accelerates?|scales?|builds?|powers?|reduces?|optimizes?)\b"
    r".{0,80}\b(?:using|with|on|via)\s+(?:amazon|aws|azure|google cloud|vertex ai)\b",
    re.I,
)

# The product taxonomy. The classifier's market_category is accepted only
# when it is exactly one of these (case-insensitive); anything else is None.
MARKET_CATEGORIES = (
    "Models", "Agents", "Coding", "Research", "Security", "Hardware", "Infrastructure",
    "Robotics", "Multimodal", "Open Source", "Policy", "Funding", "Partnerships",
)
_MARKET_CATEGORY_KEYS = {label.lower(): label for label in MARKET_CATEGORIES}


def normalize_market_category(label) -> Optional[str]:
    """A classifier label as a taxonomy category, or None. Never guesses a near match."""
    if not isinstance(label, str):
        return None
    return _MARKET_CATEGORY_KEYS.get(" ".join(label.split()).lower())


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
    primary_source_tier: str = ""
    # Publisher readers should see: the validated originating publisher
    # behind an aggregator link, otherwise the ingest source.
    display_source_name: str = ""
    # The classifier's market_category, already normalized to MARKET_CATEGORIES.
    classified_category: str = ""
    # Sanitized stored image URL; the card only says whether one is usable.
    image_url: str = ""


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
    One category from the event's primary subject.

    A stored specific kind (model release, research, open source, hardware)
    is that subject. A headline word such as "agent" does not recategorize it.
    Headline rules apply when the kind is generic, and a summary mention never does.
    Security language in the headline still wins, because those words name the incident.
    """
    kind = (event.event_kind or "other").strip().lower()
    headline = _HYPHENS.sub("-", event.headline or "")
    if _HEADLINE_SECURITY.search(headline):
        return "Security"
    if kind == "security_incident":
        if _SECURITY_TERMS.search(headline) or _SECURITY_TERMS.search(event.summary or ""):
            return "Security"
        kind = "other"
    mapped = _KIND_CATEGORY.get(kind)
    if mapped:
        return mapped
    # Generic kinds (capability, tool_update, other, ...) name no market area;
    # the classifier's taxonomy answer does. Security still needs security
    # language, as for the security_incident kind above.
    classified = normalize_market_category(event.classified_category)
    if classified and classified != "Security":
        return classified
    if _HEADLINE_PERSONNEL.search(headline):
        return None
    if _HEADLINE_POLICY.search(headline):
        return "Policy"
    for label, pattern in _CATEGORY_RULES:
        if pattern.search(headline):
            return label
    if _HEADLINE_CODING.search(headline):
        return "Coding"
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
    for label, pattern in _NAMED_AREA_RULES:
        if pattern.search(headline):
            return label
    return None


def _substance(event: MarketEvent) -> int:
    kind = (event.event_kind or "other").strip().lower()
    category = market_category(event) or ""
    return max(_SUBSTANCE.get(kind, 0), _CATEGORY_SUBSTANCE.get(category, 0))


_HIGH_KINDS = {
    "model_release",
    "model_family",
    "hardware_platform",
    "security_incident",
    "research",
    "benchmark",
    "open_source_release",
    "funding",
    "acquisition",
}

_DISTRIBUTION = re.compile(r"\b(available on|now available|released on)\b", re.I)


def is_significant_development(event: MarketEvent) -> bool:
    """Importance band, excluding customer deployments and roundups."""
    if event.importance < 70:
        return False
    if is_roundup(event) or _is_customer_deployment(event):
        return False
    return True


def is_substantive_development(event: MarketEvent) -> bool:
    """
    A reader-level development, not a discussion, roundup, or customer post.

    Publisher volume alone does not qualify. A stored high-substance kind
    does, and so does importance >= 70 when the headline supports a category.
    """
    if is_discussion(event) or is_roundup(event) or _is_customer_deployment(event):
        return False
    kind = (event.event_kind or "other").strip().lower()
    if kind == "partnership":
        return False
    if kind in _HIGH_KINDS and event.importance >= 50:
        return True
    return event.importance >= 70 and bool(market_category(event))


def importance_label(score: int) -> str:
    if score >= 90:
        return "Major"
    if score >= 70:
        return "Significant"
    if score >= 50:
        return "Notable"
    return "Minor"


def source_availability(event: MarketEvent) -> str:
    """Provenance from stored source tiers. Event kind is not a source."""
    tier = _best_tier(event)
    if tier == "primary":
        return "Official source"
    if tier == "research":
        return "Research"
    if tier == "secondary":
        return "News coverage"
    if tier == "community":
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


_GENERIC_LEAD = {"ai", "the", "a", "an", "new"}


def _is_proper_name(entity: str) -> bool:
    """
    "Enveda", "Jensen Huang", "GPT-6 Sol" name someone. "AI agents" and
    "AI biotech" describe a kind of thing; shown as the subject they read as
    an organization that does not exist.
    """
    for word in entity.replace("/", " ").split():
        if word.lower() in _GENERIC_LEAD:
            continue
        if word[:1].isupper() or word[:1].isdigit():
            return True
    return False


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
        if cleaned and _is_proper_name(cleaned):
            return cleaned
    # A news outlet or aggregator is who reported it, not who did it.
    # Only a curated primary or research publisher is its own subject.
    if (event.primary_source_tier or "").strip().lower() in {"primary", "research"}:
        return event.organization_name or event.primary_source_name or ""
    return ""


def _has_usable_image(url: str) -> bool:
    from app.core.presentation import classify_image_role

    return bool(url) and classify_image_role(url) != "none"


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
        "source_name": event.display_source_name or event.primary_source_name,
        "has_image": _has_usable_image(event.image_url),
    }


def _best_tier(event: MarketEvent) -> str:
    tiers = {(tier or "").lower() for tier in event.source_tiers}
    if "primary" in tiers:
        return "primary"
    if "research" in tiers:
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
    headline = event.headline or ""
    return bool(_CUSTOMER_DEPLOYMENT.search(headline) or _CUSTOMER_ON_PLATFORM.search(headline))


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


@lru_cache(maxsize=100_000)
def _headline_relationship(left: str, right: str, left_kind: str, right_kind: str) -> str:
    """
    Memoized headline relationship. The classifier is a pure function of
    these four strings, and one overview build compares the same pairs
    several times (the week, then each subset). Stored headlines rarely
    change, so later requests reuse earlier results as well.
    """
    return classify_headline_relationship(left, right, left_kind, right_kind)


def _same_reader_development(left: MarketEvent, right: MarketEvent) -> bool:
    """One underlying development, including a later distribution of a release."""
    relationship = _headline_relationship(
        left.headline or "",
        right.headline or "",
        left.event_kind or "",
        right.event_kind or "",
    )
    return relationship in {
        EventRelationship.SAME_EVENT,
        EventRelationship.UPDATE_TO_SAME_EVENT,
    }


def _cluster_map(events: list[MarketEvent]) -> dict[str, str]:
    """Map event id to a stable cluster id. Related headlines share an id."""
    parent = {event.id: event.id for event in events}

    def find(event_id: str) -> str:
        while parent[event_id] != event_id:
            parent[event_id] = parent[parent[event_id]]
            event_id = parent[event_id]
        return event_id

    for index, left in enumerate(events):
        for right in events[index + 1 :]:
            if not _same_reader_development(left, right):
                continue
            left_root = find(left.id)
            right_root = find(right.id)
            if left_root != right_root:
                parent[right_root] = left_root
    return {event.id: find(event.id) for event in events}


def _representative(group: list[MarketEvent], moment: datetime) -> MarketEvent:
    def key(event: MarketEvent) -> tuple:
        distribution = 1 if _DISTRIBUTION.search(event.headline or "") else 0
        return (0 if distribution else 1, _quality_key(event, moment))

    return max(group, key=key)


def _representatives(events: list[MarketEvent], moment: datetime) -> list[MarketEvent]:
    if not events:
        return []
    clusters = _cluster_map(events)
    grouped: dict[str, list[MarketEvent]] = {}
    for event in events:
        grouped.setdefault(clusters[event.id], []).append(event)
    return [_representative(group, moment) for group in grouped.values()]


def _select_diverse(
    events: list[MarketEvent],
    moment: datetime,
    limit: int,
    per_org: int,
    per_category: int,
) -> list[MarketEvent]:
    ranked = sorted(events, key=lambda event: _quality_key(event, moment), reverse=True)
    chosen: list[MarketEvent] = []
    orgs: dict[str, int] = {}
    categories: dict[str, int] = {}
    for event in ranked:
        org = _display_organization(event) or event.id
        category = market_category(event) or ""
        if orgs.get(org, 0) >= per_org:
            continue
        if category and categories.get(category, 0) >= per_category:
            continue
        orgs[org] = orgs.get(org, 0) + 1
        if category:
            categories[category] = categories.get(category, 0) + 1
        chosen.append(event)
        if len(chosen) == limit:
            break
    return chosen


def _select_now(events: list[MarketEvent], moment: datetime) -> list[MarketEvent]:
    """
    Up to six significant developments. A short list is left short.

    One organization and one category first. A second item in a category
    is allowed only when it is itself a major substantive development
    from a different organization. Notable items are not used to fill
    the section out to six.
    """
    ranked = sorted(events, key=lambda event: _quality_key(event, moment), reverse=True)
    qualified = [event for event in ranked if event.importance >= 70]
    # Major releases are placed before other high-substance items, so a
    # second model introduction is not pushed out by an earlier item from
    # the same organization.
    majors = [event for event in qualified if event.importance >= 80]
    core = [event for event in qualified if event.importance < 80 and _substance(event) >= 3]
    chosen: list[MarketEvent] = []
    orgs: dict[str, int] = {}
    categories: dict[str, int] = {}
    deferred: list[MarketEvent] = []

    def take(event: MarketEvent) -> None:
        org = _display_organization(event) or event.id
        category = market_category(event) or ""
        orgs[org] = orgs.get(org, 0) + 1
        if category:
            categories[category] = categories.get(category, 0) + 1
        chosen.append(event)

    def place(group: list[MarketEvent], *, defer: bool) -> None:
        for event in group:
            if len(chosen) >= 6:
                break
            org = _display_organization(event) or event.id
            category = market_category(event) or ""
            if orgs.get(org, 0) >= 1:
                continue
            if category and categories.get(category, 0) >= 1:
                if defer:
                    deferred.append(event)
                continue
            take(event)

    place(majors, defer=True)
    for event in deferred:
        if len(chosen) >= 6:
            break
        if event.importance < 80 or _substance(event) < 3:
            continue
        org = _display_organization(event) or event.id
        category = market_category(event) or ""
        if orgs.get(org, 0) >= 1:
            continue
        if category and categories.get(category, 0) >= 2:
            continue
        take(event)
    seen = {event.id for event in chosen}
    for event in qualified:
        if len(chosen) >= 6:
            break
        if event.id in seen:
            continue
        org = _display_organization(event) or event.id
        category = market_category(event) or ""
        if orgs.get(org, 0) >= 1:
            continue
        if category and categories.get(category, 0) >= 1:
            continue
        take(event)
    chosen.sort(key=lambda event: _quality_key(event, moment), reverse=True)
    return chosen[:6]


def _is_emerging(recent_clusters: int, week_clusters: int, publishers: int) -> bool:
    """
    Internal signal: recent activity is a large share of this week's
    distinct developments, from more than one publisher.

    There is no earlier baseline in the feed, so this compares the last
    36 hours with the current week only.
    """
    if week_clusters < 2 or recent_clusters < 2 or publishers < 2:
        return False
    return (recent_clusters / week_clusters) >= 0.4


def _distinct_sources(events: list[MarketEvent]) -> int:
    names = {name for event in events for name in event.source_names if name}
    if names:
        return len(names)
    return len({event.primary_source_name for event in events if event.primary_source_name})


def _example_cards(events: list[MarketEvent], moment: datetime) -> list[dict]:
    ranked = sorted(
        _representatives(events, moment),
        key=lambda event: _quality_key(event, moment),
        reverse=True,
    )
    examples = []
    seen_orgs: set[str] = set()
    for event in ranked:
        if is_discussion(event) or is_roundup(event) or _is_customer_deployment(event):
            continue
        org = _display_organization(event) or event.id
        if org in seen_orgs:
            continue
        seen_orgs.add(org)
        examples.append({"id": event.id, "headline": event.headline})
        if len(examples) == 2:
            break
    return examples


def build_market_overview(events: list[MarketEvent], now: Optional[datetime] = None) -> dict:
    """
    Current-week overview.

    Counts that describe the market are distinct reader-level developments.
    Repeated coverage of the same headline cluster counts once.
    Now is the last 36 hours. A distribution post does not take a second
    Now slot when the announcement is already represented.
    """
    moment = _utc(now or datetime.now(timezone.utc))
    prepared = [event for event in events if event.occurred_at is not None]
    prepared.sort(key=lambda event: _utc(event.occurred_at), reverse=True)
    clusters = _cluster_map(prepared)

    def in_now(event: MarketEvent) -> bool:
        return _within(event, moment, NOW_WINDOW)

    window = [event for event in prepared if in_now(event)]
    direct = [
        event for event in window
        if not is_discussion(event)
        and not is_roundup(event)
        and not _is_customer_deployment(event)
        and event.importance >= 70
    ]
    now_pool = _representatives(direct, moment)
    happening = _select_now(now_pool, moment)
    happening_ids = {event.id for event in happening}
    happening_clusters = {clusters[event.id] for event in happening}

    biggest_pool = [
        event for event in prepared
        if event.id not in happening_ids
        and clusters[event.id] not in happening_clusters
        and event.importance >= 70
        and not is_discussion(event)
        and not is_roundup(event)
        and not _is_customer_deployment(event)
    ]
    biggest = _select_diverse(_representatives(biggest_pool, moment), moment, 4, 1, 2)

    by_category: dict[str, list[MarketEvent]] = {}
    for event in prepared:
        category = market_category(event)
        if not category:
            continue
        by_category.setdefault(category, []).append(event)

    pulse = []
    trending = []
    for label, group in by_category.items():
        substantive = [event for event in group if is_substantive_development(event)]
        cluster_ids = {clusters[event.id] for event in substantive}
        if not cluster_ids:
            continue
        recent_ids = {clusters[event.id] for event in substantive if in_now(event)}
        sources = _distinct_sources(substantive)
        emerging = _is_emerging(len(recent_ids), len(cluster_ids), sources)
        row = {
            "label": label,
            "week": len(cluster_ids),
            "sources": sources,
            "emerging": emerging,
        }
        if recent_ids:
            row["recent"] = len(recent_ids)
        if emerging or (len(cluster_ids) >= 2 and sources >= 2 and recent_ids):
            row["examples"] = _example_cards(substantive, moment)
        pulse.append(row)
        if len(cluster_ids) >= 2 and sources >= 2 and recent_ids:
            trending.append({
                "label": label,
                "week": len(cluster_ids),
                "sources": sources,
                "recent": len(recent_ids),
                "emerging": emerging,
            })
    pulse.sort(key=lambda item: (-int(item["emerging"]), -item["week"], item["label"]))
    for row in pulse:
        row.pop("emerging", None)
    trending.sort(key=lambda item: (-int(item["emerging"]), -item["recent"], -item["week"], item["label"]))
    for row in trending:
        row.pop("emerging", None)
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
        substantive = [event for event in group if is_substantive_development(event)]
        latest_pool = substantive or group
        latest = max(latest_pool, key=lambda event: _utc(event.occurred_at))
        category_counts: dict[str, int] = {}
        for event in substantive or group:
            category = market_category(event)
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1
        top_categories = [
            label for label, _count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        ][:2]
        recent = sum(1 for event in substantive if in_now(event))
        player = {
            "slug": slug,
            "name": name,
            "week": len(group),
            "substantive": len(substantive),
            "significant": sum(1 for event in group if is_significant_development(event)),
            "sources": _distinct_sources(group),
            "latest_headline": latest.headline,
            "latest_event_id": latest.id,
            "latest_time": _utc(latest.occurred_at).isoformat(),
            "categories": top_categories,
            "event_ids": [event.id for event in sorted(group, key=lambda item: _utc(item.occurred_at), reverse=True)],
        }
        if recent:
            player["recent"] = recent
        players.append(player)
    players.sort(key=lambda item: (-item["substantive"], -item["sources"], -item["week"], item["name"]))

    return {
        "as_of": moment.isoformat(),
        "happening_now": [_card(event) for event in happening],
        "trending": trending,
        "biggest": [_card(event) for event in biggest],
        "pulse": pulse,
        "players": players[:8],
    }
