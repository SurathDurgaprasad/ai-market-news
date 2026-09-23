"""
Load the curated source registry into SQLite.

Usage (from the backend/ directory):

    python seed_sources.py

The list lives in sources.registry.json. This script does not contain
source-specific parsing. Running it again updates URLs and tiers in place
and does not re-enable a source that was disabled.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.db.base_class import Base
from app.db.session import SessionLocal, engine
from app.core.registry import seed_from_registry

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Creating tables if they don't exist...")
    Base.metadata.create_all(bind=engine)
    from app.db.session import ensure_sqlite_columns
    ensure_sqlite_columns(engine)

    db = SessionLocal()
    try:
        inserted, updated = seed_from_registry(db)
    finally:
        db.close()
    logger.info("Done. Inserted: %s, Updated: %s", inserted, updated)


if __name__ == "__main__":
    main()
