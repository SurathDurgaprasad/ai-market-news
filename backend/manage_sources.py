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
    python manage_sources.py repair-versions [--refetch] [--apply]
    python manage_sources.py recheck-duplicates [--max-checks N] [--apply]
    python manage_sources.py backfill-categories [--run FILE | --apply FILE | --revert]
    python manage_sources.py llm-usage [--hours N]
    python manage_sources.py repair-digests [--apply]
    python manage_sources.py rebuild-digest-card --event ID --run FILE | --apply FILE

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


def _live_text_lookup(db):
    """
    Text today's pipeline would store for a URL: the feed body when the
    source's feed carries one, otherwise the extracted page. Feeds are read
    once, on first use.
    """
    from app.core.article_body import MIN_CONTENT_CHARS, enrich_article
    from app.core.deduplication import normalize_url
    from app.core.fetcher import fetch_url
    from app.core.parser import parse_rss_feed
    from app.models.source import Source

    bodies: dict = {}
    loaded = []

    def lookup(url: str):
        if not loaded:
            loaded.append(True)
            for (feed_url,) in db.query(Source.url).filter(Source.enabled.is_(True)).all():
                try:
                    for item in parse_rss_feed(fetch_url(feed_url).text):
                        bodies.setdefault(normalize_url(item.url), item.content)
                except Exception as exc:  # one dead feed does not stop the repair
                    print(f"feed skipped: {feed_url} ({type(exc).__name__})")
        body = bodies.get(normalize_url(url), "")
        text, _image, _publisher = enrich_article("", url, body, fetch_fn=fetch_url)
        return text if len(text) >= 4 * MIN_CONTENT_CHARS else None

    return lookup


def cmd_repair_versions(args) -> int:
    from app.core.consolidate import repair_churn_versions

    db = _ready()
    try:
        refetch = None
        if args.refetch:
            refetch = _live_text_lookup(db)

        repaired = repair_churn_versions(db, apply=args.apply, refetch=refetch)
    finally:
        db.close()
    for headline, version in repaired:
        print(f"{'repaired' if args.apply else 'would repair'}: v{version} {headline!r}")
    print(f"{len(repaired)} churn version(s) {'repaired' if args.apply else 'found (dry run; pass --apply)'}")

    from app.core.consolidate import restore_version_evidence

    db = _ready()
    try:
        from app.core.providers.llm import get_llm_provider, resolve_llm_mode

        # Restored evidence must be the same development; without a model, nothing is restored.
        if resolve_llm_mode() != "production":
            print("No production LLM is configured; evidence restoration skipped.")
            return 0
        restored = restore_version_evidence(db, apply=args.apply, llm=get_llm_provider())
    finally:
        db.close()
    for headline, count in restored:
        print(f"{'restored' if args.apply else 'would restore'}: {count} article(s) to {headline!r}")
    print(f"{len(restored)} card(s) with evidence left on old versions")
    return 0


def cmd_recheck_duplicates(args) -> int:
    from app.core.consolidate import recheck_recent_duplicates
    from app.core.providers.llm import get_llm_provider, resolve_llm_mode

    if resolve_llm_mode() != "production":
        print("No production LLM is configured; nothing was checked.")
        return 2
    db = _ready()
    try:
        merged = recheck_recent_duplicates(
            db, get_llm_provider(), apply=args.apply, max_checks=args.max_checks
        )
    finally:
        db.close()
    for kept, duplicate in merged:
        print(f"{'merged' if args.apply else 'would merge'}: {duplicate!r} -> {kept!r}")
    print(f"{len(merged)} duplicate card(s) {'merged' if args.apply else 'found (dry run; pass --apply)'}")
    return 0


def cmd_backfill_categories(args) -> int:
    """
    Three steps, so no LLM request is made without a printed estimate and
    no database write happens without a saved, reviewable dry run:
      (default)      estimate only: events, requests, tokens, runtime. No calls.
      --run FILE     two batched passes; agreed labels saved to FILE. No writes.
      --apply FILE   store the agreed labels from FILE. No calls.
      --revert       remove every backfilled label.
    """
    import json

    from app.core.consolidate import (
        apply_category_backfill,
        category_backfill_candidates,
        classify_categories_batched,
        estimate_category_backfill,
        revert_category_backfill,
    )

    db = _ready()
    try:
        if args.revert:
            print(f"{revert_category_backfill(db)} backfilled label(s) removed")
            return 0
        if args.apply:
            with open(args.apply, encoding="utf-8") as handle:
                rows = json.load(handle)
            applied = apply_category_backfill(db, rows)
            print(f"{applied} label(s) stored from {args.apply} ({sum(1 for r in rows if r.get('label'))} agreed in the file)")
            return 0
        if args.run and os.path.exists(args.run):
            print(f"{args.run} already exists; choose a new file so a reviewed dry run is never overwritten.")
            return 2
        events = category_backfill_candidates(db, limit=args.limit)
        plan = estimate_category_backfill(events, args.batch)
        print(
            "estimate: {events} events, {requests} requests (2 passes x batches of {batch_size}), "
            "~{input_tokens} input tokens, ~{output_tokens} output tokens, ~{runtime_seconds}s".format(**plan)
        )
        if not args.run:
            print("No requests made. Pass --run FILE to classify (dry run, no database writes).")
            return 0
        from app.core.providers.llm import get_llm_provider, resolve_llm_mode

        if resolve_llm_mode() != "production":
            print("No production LLM is configured; nothing was classified.")
            return 2
        rows = classify_categories_batched(get_llm_provider(), events, batch_size=args.batch, pause_seconds=args.pause)
    finally:
        db.close()
    with open(args.run, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1)
    agreed = [row for row in rows if row["label"]]
    for row in rows:
        verdict = f"would set {row['label']}" if row["label"] else "keep none"
        print(f"{verdict:24} a={row['pass_a'] or '-':14} b={row['pass_b'] or '-':14} {row['headline'][:80]!r}")
    print(f"{len(agreed)} of {len(rows)} agreed. Saved to {args.run}; review, then --apply {args.run}")
    return 0


def cmd_llm_usage(args) -> int:
    from datetime import datetime, timedelta, timezone

    from app.core.llm_usage import ledger_path, read_ledger, summarize

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours) if args.hours else None
    rows = read_ledger(since)
    print(f"ledger: {ledger_path()}  rows: {len(rows)}")
    for operation, entry in sorted(summarize(rows).items()):
        print(
            f"{operation:28} requests={entry['requests']:5} failed={entry['failed']:4} "
            f"in={entry['input_tokens']:8} out={entry['output_tokens']:7} latency_ms={entry['latency_ms']}"
        )
    return 0


def cmd_repair_digests(args) -> int:
    from app.core.consolidate import repair_digest_events
    from app.core.providers.llm import get_llm_provider, resolve_llm_mode

    if resolve_llm_mode() != "production":
        print("No production LLM is configured; nothing was checked.")
        return 2
    db = _ready()
    try:
        repaired = repair_digest_events(db, get_llm_provider(), apply=args.apply)
    finally:
        db.close()
    fixed = 0
    for headline, old, new, status in repaired:
        if status == "repaired":
            fixed += 1
            print(f"{'repaired' if args.apply else 'would repair'}: {headline[:80]!r} entities {old} -> {new}")
        else:
            print(f"skipped ({status}; needs a new summary): {headline[:80]!r} entities {old}")
    print(f"{fixed} digest card(s) {'repaired' if args.apply else 'to repair (dry run; pass --apply)'}")
    return 0


def cmd_rebuild_digest_card(args) -> int:
    """
    --run FILE: two LLM requests, proposal saved to FILE, no database write
    (the session is never committed and is discarded on close).
    --apply FILE: store a reviewed proposal, no requests.
    """
    import json

    from app.core.consolidate import apply_digest_rebuild, propose_digest_rebuild

    if args.run and not args.event:
        print("--run needs --event ID; nothing was requested.")
        return 2
    if args.run and os.path.exists(args.run):
        print(f"{args.run} already exists; choose a new file so a reviewed proposal is never overwritten.")
        return 2
    db = _ready()
    try:
        if args.apply:
            with open(args.apply, encoding="utf-8") as handle:
                print(apply_digest_rebuild(db, json.load(handle)))
            return 0
        from app.core.providers.llm import get_llm_provider, resolve_llm_mode

        if resolve_llm_mode() != "production":
            print("No production LLM is configured; nothing was rebuilt.")
            return 2
        print("estimate: 2 requests (classify + summarize of the lead story)")
        proposal = propose_digest_rebuild(db, get_llm_provider(), args.event)
    finally:
        db.close()
    with open(args.run, "w", encoding="utf-8") as handle:
        json.dump(proposal, handle, indent=1, default=str)
    print(f"{proposal['status']}: saved to {args.run}")
    if proposal["status"] == "proposed":
        print(f"  old: {proposal['old']['headline']!r} entities {proposal['old']['entities']}")
        print(f"  new: {proposal['new']['headline']!r} entities {proposal['new']['entities']}")
        print(f"  citations: {proposal['new']['citations']}")
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
    versions.add_argument(
        "--refetch",
        action="store_true",
        help="Also compare the first version with the live page under today's extractor",
    )
    versions.set_defaults(func=cmd_repair_versions)

    recheck = sub.add_parser(
        "recheck-duplicates",
        help="Ask the relationship model about recent cards ingestion never compared",
    )
    recheck.add_argument("--apply", action="store_true")
    recheck.add_argument("--max-checks", type=int, default=60)
    recheck.set_defaults(func=cmd_recheck_duplicates)

    backfill = sub.add_parser(
        "backfill-categories",
        help="Categorize live events stored before the classifier returned a market category",
    )
    step = backfill.add_mutually_exclusive_group()
    step.add_argument("--run", metavar="FILE", help="Classify (two batched passes) and save the dry run to FILE")
    step.add_argument("--apply", metavar="FILE", help="Store the agreed labels from a saved dry run")
    step.add_argument("--revert", action="store_true", help="Remove every backfilled label")
    backfill.add_argument("--limit", type=int, default=300)
    backfill.add_argument("--batch", type=int, default=20)
    backfill.add_argument("--pause", type=float, default=3.0, help="Seconds between requests (provider rate limit)")
    backfill.set_defaults(func=cmd_backfill_categories)

    usage = sub.add_parser("llm-usage", help="Summarize provider requests from the usage ledger")
    usage.add_argument("--hours", type=float, default=0, help="Only the last N hours (default: all)")
    usage.set_defaults(func=cmd_llm_usage)

    digests = sub.add_parser(
        "repair-digests",
        help="Reclassify newsletter-digest cards whose entities came from another story",
    )
    digests.add_argument("--apply", action="store_true")
    digests.set_defaults(func=cmd_repair_digests)

    rebuild = sub.add_parser(
        "rebuild-digest-card",
        help="Rebuild a digest card whose headline came from the roundup, from the lead story",
    )
    rebuild.add_argument("--event", required=False)
    rebuild_step = rebuild.add_mutually_exclusive_group(required=True)
    rebuild_step.add_argument("--run", metavar="FILE")
    rebuild_step.add_argument("--apply", metavar="FILE")
    rebuild.set_defaults(func=cmd_rebuild_digest_card)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RegistryError as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
