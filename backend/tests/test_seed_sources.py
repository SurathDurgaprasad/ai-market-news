"""
Live-run finding (2026-09-23): re-seeding the source registry after a
stale feed URL was corrected (e.g. OpenAI Blog: openai.com/blog/rss.xml
-> openai.com/news/rss.xml) created a SECOND "OpenAI Blog" row instead of
updating the existing one, because seed()'s upsert matched by URL alone.
The old, now-dead-URL row was left behind as a permanent duplicate,
visibly confusing on the real admin sources page (two "OpenAI Blog"
entries, one healthy, one failing/Never fetched) and contradicting the
script's own documented "idempotent" contract.

Reproduced directly against the real seed() function (not assumed) before
fixing, then fixed by matching on (organization, name) first, falling
back to URL, and updating url in place on a match.
"""
import uuid

from app.core.registry import seed_from_registry as seed
from app.models.source import Source, Organization


def test_reseeding_after_a_url_correction_updates_in_place_not_duplicates(db_session):
    org = Organization(id=uuid.uuid4(), name="OpenAI")
    db_session.add(org)
    db_session.flush()
    original = Source(
        id=uuid.uuid4(),
        name="OpenAI Blog",
        url="https://openai.com/blog/rss.xml",  # the old, since-corrected URL
        organization_id=org.id,
        type="rss",
        tier="primary",
        polling_tier="high",
        enabled=True,
        health_status="healthy",
    )
    db_session.add(original)
    db_session.commit()
    original_id = original.id

    seed(db_session)

    rows = db_session.query(Source).filter(Source.name == "OpenAI Blog").all()
    assert len(rows) == 1, (
        f"expected re-seeding to update the existing OpenAI Blog row in place, "
        f"got {len(rows)} rows — a URL correction must not orphan a duplicate"
    )
    assert rows[0].id == original_id, "the original row's identity must be preserved, not replaced"
    assert rows[0].url == "https://openai.com/news/rss.xml", "the URL must be updated to the current curated value"


def test_seed_is_idempotent_across_two_runs(db_session):
    seed(db_session)
    first_total = db_session.query(Source).count()

    seed(db_session)
    second_total = db_session.query(Source).count()

    assert first_total == second_total, "running seed() twice in a row must not change the source count"

    names = [s.name for s in db_session.query(Source).all()]
    assert len(names) == len(set(names)), "seed() must never produce two sources with the same name"


def test_url_correction_matches_a_row_that_has_no_organization(db_session):
    original = Source(
        id=uuid.uuid4(),
        name="Google DeepMind Blog",
        url="https://deepmind.google/blog/rss",
        organization_id=None,
        type="rss",
        tier="primary",
        polling_tier="high",
        enabled=True,
        health_status="failing",
    )
    db_session.add(original)
    db_session.commit()
    original_id = original.id

    seed(db_session)

    rows = db_session.query(Source).filter(Source.name == "Google DeepMind Blog").all()
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].url == "https://deepmind.google/blog/rss.xml"
    assert rows[0].organization is not None
    assert rows[0].organization.name == "Google DeepMind"


def test_seed_does_not_reenable_a_disabled_source(db_session):
    seed(db_session)
    row = db_session.query(Source).filter(Source.name == "OpenAI Blog").one()
    row.enabled = False
    db_session.commit()

    seed(db_session)

    db_session.refresh(row)
    assert row.enabled is False
