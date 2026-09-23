"""
Data-driven source registry.

The scheduler ingests every enabled RSS row in the database. Adding a source
is an insert or an update of that row. It does not require a parser, a
migration, or a change to the scheduler.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.core.urls import sanitize_http_url
from app.models.source import Organization, Source

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "sources.registry.json"

VALID_TIERS = {"primary", "research", "secondary", "community"}
VALID_POLLING = {"high", "medium", "low"}


class RegistryError(ValueError):
    """A source record was rejected before it touched the database."""


def load_registry(path: Optional[Path] = None) -> list[dict]:
    target = path or REGISTRY_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RegistryError(f"{target} must be a JSON list of sources")
    return raw


def _clean_url(url: str) -> str:
    cleaned = sanitize_http_url((url or "").strip(), keep_query=True)
    if not cleaned:
        raise RegistryError(f"Source URL is not a public http(s) address: {url!r}")
    return cleaned


def _require(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise RegistryError(f"{label} is required")
    return text


def get_or_create_organization(db: Session, name: str) -> Organization:
    org_name = _require(name, "Organization")
    org = db.query(Organization).filter(Organization.name == org_name).first()
    if org:
        return org
    org = Organization(id=uuid.uuid4(), name=org_name)
    db.add(org)
    db.flush()
    return org


def upsert_source(
    db: Session,
    *,
    organization: str,
    name: str,
    url: str,
    tier: str = "secondary",
    polling_tier: str = "medium",
    enabled: bool = True,
    update_enabled: bool = False,
) -> tuple[Source, str]:
    """
    Insert a source or update the existing row.

    Identity is (organization, name), then URL. A repeated add does not
    create a second row. `update_enabled=False` leaves an operator's
    enabled/disabled choice in place when the curated file is re-seeded.
    Returns (source, "inserted" | "updated").
    """
    source_name = _require(name, "Name")
    cleaned = _clean_url(url)
    kind = (tier or "").strip().lower()
    if kind not in VALID_TIERS:
        raise RegistryError(f"tier must be one of {sorted(VALID_TIERS)}")
    cadence = (polling_tier or "").strip().lower()
    if cadence not in VALID_POLLING:
        raise RegistryError(f"polling_tier must be one of {sorted(VALID_POLLING)}")

    org = get_or_create_organization(db, organization)
    by_identity = (
        db.query(Source)
        .filter(Source.organization_id == org.id, Source.name == source_name)
        .first()
    )
    by_url = db.query(Source).filter(Source.url == cleaned).first()
    by_name = db.query(Source).filter(Source.name == source_name).all()
    # A row created before its organization was recorded still has this name.
    # Matching it avoids a second "same blog, new URL" row.
    by_unique_name = by_name[0] if len(by_name) == 1 else None
    if by_identity and by_url and by_identity.id != by_url.id:
        raise RegistryError(
            f"URL {cleaned} already belongs to source {by_url.name!r}"
        )
    existing = by_identity or by_url or by_unique_name
    if existing and by_url and existing.id != by_url.id:
        raise RegistryError(
            f"URL {cleaned} already belongs to source {by_url.name!r}"
        )
    if existing:
        existing.name = source_name
        existing.organization_id = org.id
        existing.url = cleaned
        existing.tier = kind
        existing.polling_tier = cadence
        existing.type = existing.type or "rss"
        if (existing.type or "").lower() != "rss":
            existing.type = "rss"
        if update_enabled:
            existing.enabled = bool(enabled)
        return existing, "updated"

    source = Source(
        id=uuid.uuid4(),
        name=source_name,
        url=cleaned,
        organization_id=org.id,
        type="rss",
        tier=kind,
        polling_tier=cadence,
        enabled=bool(enabled),
        health_status="healthy",
    )
    db.add(source)
    db.flush()
    return source, "inserted"


def set_enabled(db: Session, *, name: str, enabled: bool) -> Source:
    source_name = _require(name, "Name")
    matches = db.query(Source).filter(Source.name == source_name).all()
    if not matches:
        raise RegistryError(f"No source named {source_name!r}")
    if len(matches) > 1:
        raise RegistryError(
            f"More than one source is named {source_name!r}; disable by editing the row url"
        )
    matches[0].enabled = bool(enabled)
    if not enabled:
        matches[0].health_status = "disabled"
    elif (matches[0].health_status or "").lower() == "disabled":
        matches[0].health_status = "healthy"
    return matches[0]


def seed_from_registry(db: Session, path: Optional[Path] = None) -> tuple[int, int]:
    """Load the curated JSON file. Does not re-enable a source an operator disabled."""
    inserted = 0
    updated = 0
    for record in load_registry(path):
        if not isinstance(record, dict):
            raise RegistryError("Each registry entry must be an object")
        _source, action = upsert_source(
            db,
            organization=str(record.get("organization") or ""),
            name=str(record.get("name") or ""),
            url=str(record.get("url") or ""),
            tier=str(record.get("tier") or "secondary"),
            polling_tier=str(record.get("polling_tier") or "medium"),
            enabled=bool(record.get("enabled", True)),
            update_enabled=False,
        )
        if action == "inserted":
            inserted += 1
        else:
            updated += 1
    db.commit()
    return inserted, updated
