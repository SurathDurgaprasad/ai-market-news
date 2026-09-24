"""
Operate the source registry without changing application code.

From the backend/ directory:

    python manage_sources.py list
    python manage_sources.py add --organization "OpenAI" --name "OpenAI Research" --url "https://example.com/feed.xml" --tier research
    python manage_sources.py disable --name "OpenAI Research"
    python manage_sources.py enable --name "OpenAI Research"
    python manage_sources.py update --name "OpenAI Research" --url "https://example.com/new.xml"
    python manage_sources.py ingest
    python manage_sources.py repair-headlines [--apply]
    python manage_sources.py repair-versions [--apply]

`ingest` runs one scheduler cycle immediately. The running API also picks up
enabled rows on its next tick. Disabled rows are not fetched.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.core.registry import RegistryError, set_enabled, upsert_source
from app.db.base_class import Base
from app.db.session import SessionLocal, engine, ensure_sqlite_columns
from app.models.source import Source

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def _ready():
    Base.metadata.create_all(bind=engine)
    ensure_sqlite_columns(engine)
    return SessionLocal()


def _print_source(source: Source) -> None:
    print(
        f"{'on' if source.enabled else 'off':3}  {source.health_status or '-':10}  "
        f"{source.tier:10}  {source.name}  {source.url}"
    )


def cmd_list(_args) -> int:
    db = _ready()
    try:
        rows = db.query(Source).order_by(Source.enabled.desc(), Source.name).all()
        print(f"{len(rows)} sources")
        for row in rows:
            _print_source(row)
    finally:
        db.close()
    return 0


def cmd_add(args) -> int:
    db = _ready()
    try:
        source, action = upsert_source(
            db,
            organization=args.organization,
            name=args.name,
            url=args.url,
            tier=args.tier,
            polling_tier=args.polling_tier,
            enabled=not args.disabled,
            update_enabled=True,
        )
        db.commit()
        logger.info("%s %s", action, source.name)
        _print_source(source)
    finally:
        db.close()
    return 0


def cmd_set(args, enabled: bool) -> int:
    db = _ready()
    try:
        source = set_enabled(db, name=args.name, enabled=enabled)
        db.commit()
        _print_source(source)
    finally:
        db.close()
    return 0


def cmd_update(args) -> int:
    db = _ready()
    try:
        current = db.query(Source).filter(Source.name == args.name).one_or_none()
        if current is None:
            raise RegistryError(f"No source named {args.name!r}")
        org_name = current.organization.name if current.organization else args.name
        source, action = upsert_source(
            db,
            organization=org_name,
            name=args.name,
            url=args.url or current.url,
            tier=args.tier or current.tier,
            polling_tier=args.polling_tier or current.polling_tier or "medium",
            enabled=current.enabled,
            update_enabled=False,
        )
        db.commit()
        logger.info("%s %s", action, source.name)
        _print_source(source)
    finally:
        db.close()
    return 0


def cmd_ingest(_args) -> int:
    from app.core.scheduler import scheduler

    result = scheduler.run_ingestion_cycle()
    if result:
        print(result)
    return 0


def cmd_repair_headlines(args) -> int:
    from app.core.headlines import repair_stored_headlines

    db = _ready()
    try:
        changes = repair_stored_headlines(db, apply=args.apply)
    finally:
        db.close()
    for old, new in changes:
        print(f"{'fixed' if args.apply else 'would fix'}: {old!r} -> {new!r}")
    print(f"{len(changes)} headline(s) {'updated' if args.apply else 'to update (dry run; pass --apply)'}")
    return 0


def cmd_repair_versions(args) -> int:
    from app.core.consolidate import repair_churn_versions

    db = _ready()
    try:
        repaired = repair_churn_versions(db, apply=args.apply)
    finally:
        db.close()
    for headline, version in repaired:
        print(f"{'repaired' if args.apply else 'would repair'}: v{version} {headline!r}")
    print(f"{len(repaired)} churn version(s) {'repaired' if args.apply else 'found (dry run; pass --apply)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage intelligence sources")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show every source").set_defaults(func=cmd_list)

    add = sub.add_parser("add", help="Insert or update a source")
    add.add_argument("--organization", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--url", required=True)
    add.add_argument("--tier", default="secondary", choices=["primary", "research", "secondary", "community"])
    add.add_argument("--polling-tier", default="medium", choices=["high", "medium", "low"])
    add.add_argument("--disabled", action="store_true")
    add.set_defaults(func=cmd_add)

    disable = sub.add_parser("disable", help="Stop ingestion for a source")
    disable.add_argument("--name", required=True)
    disable.set_defaults(func=lambda args: cmd_set(args, False))

    enable = sub.add_parser("enable", help="Resume ingestion for a source")
    enable.add_argument("--name", required=True)
    enable.set_defaults(func=lambda args: cmd_set(args, True))

    update = sub.add_parser("update", help="Change a source URL or tier")
    update.add_argument("--name", required=True)
    update.add_argument("--url")
    update.add_argument("--tier", choices=["primary", "research", "secondary", "community"])
    update.add_argument("--polling-tier", choices=["high", "medium", "low"])
    update.set_defaults(func=cmd_update)

    sub.add_parser("ingest", help="Run one ingestion cycle now").set_defaults(func=cmd_ingest)

    repair = sub.add_parser(
        "repair-headlines",
        help="Restore a confidently known organization in placeholder headlines",
    )
    repair.add_argument("--apply", action="store_true")
    repair.set_defaults(func=cmd_repair_headlines)

    versions = sub.add_parser(
        "repair-versions",
        help="Restore first-recorded time on versions created only by page counters",
    )
    versions.add_argument("--apply", action="store_true")
    versions.set_defaults(func=cmd_repair_versions)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RegistryError as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
