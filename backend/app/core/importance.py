"""
Deterministic importance gates and calibration.

The LLM score is not assumed calibrated. These helpers:
- reject obvious clickbait before an LLM call
- coerce/validate scores into 1-100 (0 = drop)
- map structured event signals onto score bands

They do not rank companies by prestige. They do not change UI thresholds
(Major >= 90, Significant >= 70, Notable >= 50, Minor < 50).
"""
from __future__ import annotations

import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

EVENT_KINDS = {
    "model_release",
    "model_family",
    "capability",
    "hardware_platform",
    "funding",
    "acquisition",
    "partnership",
    "security_incident",
    "research",
    "benchmark",
    "open_source_release",
    "tool_update",
    "migration",
    "maintenance",
    "other",
}

SCOPES = {"narrow", "product", "platform", "ecosystem"}
SECURITY = {"none", "limited", "significant"}

# Distinguishes a research survey / meta-analysis ABOUT vulnerability
# trends in aggregate from an actual vulnerability disclosure or active
# incident. Without this, infer_event_signals()'s security regex — which
# must stay broad to catch real incidents — matched "a survey of
# vulnerability trends" identically to "RCE actively exploited in the
# wild", and pipeline.py's calibration override
# (`if security == "none" and inf_sec != "none": security = inf_sec`)
# would then silently overrule an LLM that correctly said security="none"
# for a benign paper. See docs/RED_TEAM_REPORT.md IMPORTANCE-RESEARCH-01.
# Deliberately narrow (academic-survey phrasing that real incident
# reports essentially never use) to avoid the opposite failure — masking
# a genuine incident that happens to mention "study" in passing.
_VULN_RESEARCH_SURVEY_RE = re.compile(
    r"\b(survey of .*(?:vulnerabilit|trend)|literature review|systematic review|"
    r"meta-analysis|research paper|academic study|"
    r"analyz\w+ how .*(?:vulnerabilit|chang\w+)|vulnerability trends)\b",
    re.IGNORECASE,
)

# Conservative noise patterns. Do NOT match research paper titles.
_NOISE_PATTERNS = [
    re.compile(r"\btop\s+\d+\s+(ai\s+)?tools?\b", re.IGNORECASE),
    re.compile(r"you won'?t believe", re.IGNORECASE),
    re.compile(r"number \d+ will shock", re.IGNORECASE),
    re.compile(r"\b\d+\s+ai tools you must\b", re.IGNORECASE),
    re.compile(r"\bthings you need to know\b", re.IGNORECASE),
]

# (floor, preferred, ceiling) per kind/scope. Not UI thresholds — allowed scores.
_KIND_BANDS: dict[str, dict[str, tuple[int, int, int]]] = {
    "hardware_platform": {
        "ecosystem": (90, 93, 100),
        "platform": (70, 82, 89),
        "product": (70, 76, 89),
        "narrow": (50, 62, 69),
    },
    "model_family": {
        "ecosystem": (70, 86, 94),
        "platform": (70, 78, 89),
        "product": (70, 74, 85),
        "narrow": (50, 64, 69),
    },
    "model_release": {
        "ecosystem": (70, 84, 94),
        "platform": (70, 76, 89),
        "product": (50, 66, 79),
        "narrow": (50, 58, 69),
    },
    "capability": {
        "ecosystem": (70, 80, 89),
        "platform": (70, 76, 85),
        "product": (50, 64, 75),
        "narrow": (50, 56, 69),
    },
    "funding": {
        "ecosystem": (70, 82, 92),
        "platform": (70, 74, 85),
        "product": (50, 62, 75),
        "narrow": (30, 44, 55),
    },
    "acquisition": {
        "ecosystem": (90, 92, 100),
        "platform": (70, 82, 92),
        "product": (70, 74, 85),
        "narrow": (50, 60, 69),
    },
    "partnership": {
        "ecosystem": (50, 68, 79),
        "platform": (50, 64, 72),
        "product": (50, 58, 69),
        "narrow": (30, 46, 55),
    },
    "security_incident": {
        "ecosystem": (70, 84, 95),
        "platform": (70, 78, 89),
        "product": (70, 74, 85),
        "narrow": (50, 62, 69),
    },
    "research": {
        "ecosystem": (50, 68, 79),
        "platform": (50, 62, 72),
        "product": (50, 58, 69),
        "narrow": (50, 55, 65),
    },
    "benchmark": {
        "ecosystem": (50, 66, 75),
        "platform": (50, 60, 69),
        "product": (50, 56, 65),
        "narrow": (30, 48, 55),
    },
    "open_source_release": {
        "ecosystem": (70, 74, 85),
        "platform": (50, 66, 75),
        "product": (50, 58, 69),
        "narrow": (30, 48, 58),
    },
    "tool_update": {
        "ecosystem": (50, 58, 69),
        "platform": (50, 55, 65),
        "product": (50, 54, 62),
        "narrow": (30, 42, 49),
    },
    "migration": {
        "ecosystem": (50, 55, 65),
        "platform": (30, 48, 55),
        "product": (30, 42, 49),
        "narrow": (30, 36, 45),
    },
    "maintenance": {
        "ecosystem": (30, 40, 49),
        "platform": (20, 32, 45),
        "product": (15, 28, 40),
        "narrow": (10, 22, 35),
    },
    "other": {
        "ecosystem": (50, 62, 75),
        "platform": (50, 58, 69),
        "product": (50, 55, 65),
        "narrow": (30, 45, 55),
    },
}


def is_obvious_noise(title: str, content: str) -> bool:
    blob = f"{title or ''}\n{content or ''}"
    return any(p.search(blob) for p in _NOISE_PATTERNS)


def normalize_importance_score(score) -> Optional[int]:
    """
    Coerce an LLM importance score into [1, 100].

    Returns:
      None  — missing / non-numeric / zero (treat as reject)
      1-100 — usable score (out-of-range values are clamped and logged)

    Zero is reserved for "drop this item" (prompt injection / noise).
    """
    if score is None:
        return None
    try:
        value = int(score)
    except (TypeError, ValueError):
        logger.warning(f"Non-numeric importance score rejected: {score!r}")
        return None
    if value == 0:
        return None
    if value < 0 or value > 100:
        clamped = max(1, min(100, value))
        logger.warning(f"Importance score {value} outside 1-100; clamped to {clamped}")
        return clamped
    return value


def normalize_event_kind(value: Optional[str]) -> str:
    raw = (value or "other").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "model": "model_release",
        "models": "model_release",
        "family": "model_family",
        "hardware": "hardware_platform",
        "platform": "hardware_platform",
        "security": "security_incident",
        "vuln": "security_incident",
        "vulnerability": "security_incident",
        "oss": "open_source_release",
        "open_source": "open_source_release",
        "tool": "tool_update",
        "workflow": "tool_update",
        "docs": "maintenance",
        "documentation": "maintenance",
        "github": "maintenance",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in EVENT_KINDS else "other"


def normalize_scope(value: Optional[str]) -> str:
    raw = (value or "product").strip().lower()
    aliases = {"wide": "ecosystem", "global": "ecosystem", "local": "narrow", "team": "narrow"}
    raw = aliases.get(raw, raw)
    return raw if raw in SCOPES else "product"


def normalize_security(value: Optional[str]) -> str:
    raw = (value or "none").strip().lower()
    if raw in ("high", "severe", "critical", "rce"):
        raw = "significant"
    if raw in ("low", "minor"):
        raw = "limited"
    return raw if raw in SECURITY else "none"


def calibrate_importance_score(
    raw_score: Optional[int],
    event_kind: Optional[str] = None,
    technical_change_scope: Optional[str] = None,
    security_impact: Optional[str] = None,
) -> Optional[int]:
    """
    Snap a raw LLM score into the band implied by structured signals.

    If the raw score already sits in the implied band, keep it.
    If the model dumped a generic notable default (typically 50-65) onto a
    kind whose band does not include that default, move to the band floor/preferred.
    """
    score = normalize_importance_score(raw_score)
    if score is None:
        return None

    kind = normalize_event_kind(event_kind)
    scope = normalize_scope(technical_change_scope)
    security = normalize_security(security_impact)
    if security == "significant":
        kind = "security_incident"
        if scope == "narrow":
            scope = "product"

    floor, preferred, ceiling = _KIND_BANDS.get(kind, _KIND_BANDS["other"]).get(
        scope, _KIND_BANDS["other"]["product"]
    )
    if floor <= score <= ceiling:
        return score
    if score < floor:
        return floor
    # Above ceiling: compress inflated scores on low-impact kinds only.
    # Do not hide a genuine Major score (the live failure mode is default-60,
    # not default-90). Capping 95→89 turned Rubin into Significant.
    if kind in {
        "maintenance",
        "tool_update",
        "migration",
        "benchmark",
        "research",
        "partnership",
        "other",
    }:
        return ceiling
    return score


def infer_event_signals(
    headline: Optional[str],
    summary: Optional[str] = None,
    content: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    Deterministic kind/scope/security from factual text.

    Used when the LLM omitted structured fields, and for backfill.
    Does not use company-name prestige lists.
    """
    text = f"{headline or ''}\n{summary or ''}\n{(content or '')[:3000]}".lower()

    security = "none"
    if re.search(
        r"\b(rce|remote code execution|sandbox escape|compromis\w+|vulnerabilit\w+|"
        r"heap overflow|buffer overflow|exploit|account takeover|bounty)\b",
        text,
    ) and not _VULN_RESEARCH_SURVEY_RE.search(text):
        security = "significant"

    kind = "other"
    scope = "product"

    if security == "significant":
        kind = "security_incident"
        scope = "platform" if re.search(
            r"\b(infrastructure|forum|sandbox|employee account|production)\b", text
        ) else "product"
        return kind, scope, security

    if re.search(r"\bmigrat\w+\b", text) and re.search(r"\b(fortran|cobol|codebase|lines of)\b", text):
        return "migration", "narrow", security

    if re.match(r"^[\w.-]+\s+\d+(\.\d+)+\s*$", (headline or "").strip()):
        return "maintenance", "narrow", security

    if re.search(r"\bces\b", text) and re.search(r"\b(platform|architecture|blueprint)\b", text):
        return "hardware_platform", "ecosystem", security

    if re.search(r"\b(gpu architecture|new architecture|flagship gpu|accelerator platform)\b", text):
        return "hardware_platform", "platform", security

    if re.search(r"\b(acqui\w+|buys|bought|takeover)\b", text):
        scope = "ecosystem" if re.search(r"\b(billion|trillion)\b", text) else "product"
        return "acquisition", scope, security

    if re.search(r"\b(series [a-f]\b|raises \$\d|\bfunding round|valuation)\b", text):
        scope = "ecosystem" if re.search(r"\bbillion\b", text) else "product"
        return "funding", scope, security

    if re.search(r"\b(partner\w+|teams up|join forces)\b", text):
        return "partnership", "product", security

    if re.search(r"\b(model family|family of|decoder-only reasoning llms in\b|\d+b, and \d+b|\d+b, \d+b, and \d+b)\b", text):
        return "model_family", "platform", security

    if re.search(r"\b(hackathon|reproduc\w+ papers|research paper|introduces a (?:method|training pipeline)|study reveals|agentic memory|matches ace)\b", text):
        scope = "product"
        if re.search(r"\b(hackathon|community)\b", text):
            scope = "product"
        return "research", scope, security

    if re.search(r"\b(simulator|real-time generative|new capability|harness)\b", text):
        scope = "platform" if re.search(
            r"\b(real-time|surgical robotics|orchestration|benchmark-leading)\b", text
        ) else "product"
        return "capability", scope, security

    if re.search(r"\b(leaderboard|\bbenchmarks?\b)\b", text) and not re.search(
        r"\b(released|harness|benchmark-leading)\b", text
    ):
        return "benchmark", "product", security

    if re.search(r"\b(releases?|released|introduces|introduced)\b", text) and re.search(
        r"\b(\d+\s*-?\s*b\b|parameter|checkpoint|weights|instruct model|llm)\b", text
    ):
        scope = "platform" if re.search(r"\b(family|3b, 8b|open weights)\b", text) else "product"
        kind = "model_family" if "family" in text or re.search(r"\b3b, 8b\b", text) else "model_release"
        return kind, scope, security

    if re.search(r"\b(rebuilds|workflow|drag-and-drop|trainer adds|native support for)\b", text):
        scope = "narrow" if re.search(r"\b(adds loRA|adapter support|native support)\b", text) else "product"
        return "tool_update", scope, security

    if re.search(r"\b(open-source|open source|open weights)\b", text):
        return "open_source_release", "product", security

    return kind, scope, security


# Kind pairs that are NEVER the same real-world event.
# Conservative: only pairs where the combination definitively means different events.
# Uses frozensets so order doesn't matter.
_INCOMPATIBLE_KIND_PAIRS: frozenset[frozenset[str]] = frozenset({
    frozenset({"funding",       "model_release"}),
    frozenset({"funding",       "model_family"}),
    frozenset({"funding",       "hardware_platform"}),
    frozenset({"funding",       "security_incident"}),
    frozenset({"funding",       "research"}),
    frozenset({"acquisition",   "model_release"}),
    frozenset({"acquisition",   "research"}),
    frozenset({"acquisition",   "security_incident"}),
    frozenset({"maintenance",   "model_release"}),
    frozenset({"maintenance",   "model_family"}),
    frozenset({"maintenance",   "security_incident"}),
    frozenset({"maintenance",   "hardware_platform"}),
    frozenset({"maintenance",   "funding"}),
    frozenset({"maintenance",   "acquisition"}),
})


def kinds_are_compatible(kind_a: Optional[str], kind_b: Optional[str]) -> bool:
    """
    Return False when the two event kinds are provably incompatible — i.e., articles
    with these kinds can NEVER describe the same real-world event and the expensive
    LLM same-event call can be skipped.

    Returns True (compatible / unknown) when either kind is None or 'other'.
    """
    a = normalize_event_kind(kind_a)
    b = normalize_event_kind(kind_b)
    if a == "other" or b == "other":
        return True
    if a == b:
        return True
    return frozenset({a, b}) not in _INCOMPATIBLE_KIND_PAIRS


def importance_band(score: int) -> str:
    if score >= 90:
        return "MAJOR"
    if score >= 70:
        return "SIGNIFICANT"
    if score >= 50:
        return "NOTABLE"
    return "MINOR"
