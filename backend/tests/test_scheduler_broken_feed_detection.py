"""
Phase 1B, invariant 1 (source failure isolation) — a variant not yet
covered: "unexpected content type" / a feed URL that stops returning a
feed at all.

Root cause investigation: feedparser.parse() on an HTML page (a very
realistic real-world failure — a feed URL that starts 404ing, or a CMS
migration that replaces the feed with an HTML "moved" notice) returns
`bozo=False, entries=0` — feedparser does NOT flag this as malformed.
This is a materially worse silent-failure mode than a truly malformed
XML payload (feedparser's own `bozo` flag would at least catch that
case): an HTML error/notice page is INDISTINGUISHABLE, from feedparser's
own signal alone, from a legitimately well-formed feed that simply has
zero current entries.

Consequence traced through scheduler.py: `parse_rss_feed()` returns `[]`
either way, the article loop doesn't execute, `llm_blocked` stays False,
and the source is recorded `health_status="healthy"` — identical to a
source that was correctly polled and simply had nothing new. This is the
same class of defect as SCHED-OUTAGE-01 (a provider outage
indistinguishable from "no AI events found"), but one layer earlier: a
feed source that has silently stopped serving a feed at all is
indistinguishable from a feed source with no new articles.
"""
from unittest.mock import patch, MagicMock

from app.core.scheduler import IngestionScheduler
from app.models.source import Source


def _run_cycle_with_response_text(db_session, response_text: str):
    source = Source(
        name="Maybe Broken Feed",
        url="https://broken.example.com/rss",
        enabled=True,
        type="rss",
        polling_tier="high",
    )
    db_session.add(source)
    db_session.commit()
    source_id = source.id
    db_session.close = MagicMock()

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url") as mock_fetch:
            resp = MagicMock()
            resp.text = response_text
            mock_fetch.return_value = resp
            # Deliberately NOT mocking parse_rss_feed — this test exercises
            # the real parser against real (broken) content.
            scheduler.run_ingestion_cycle()

    db_session.expire_all()
    return db_session.query(Source).filter(Source.id == source_id).first()


def test_html_error_page_instead_of_feed_is_not_recorded_healthy(db_session):
    """
    THE reproduction: a source whose feed URL now serves an HTML page
    (e.g. a 404/moved notice) must not be recorded health_status="healthy"
    — that is indistinguishable from a legitimately quiet, correctly
    functioning feed and hides a real, persistent breakage from the admin
    sources page indefinitely.
    """
    html_error_page = (
        "<html><head><title>404 Not Found</title></head>"
        "<body><h1>404 Not Found</h1><p>The feed you requested has moved.</p></body></html>"
    )
    source = _run_cycle_with_response_text(db_session, html_error_page)

    assert source.health_status != "healthy", (
        "A source returning an HTML page instead of a feed was recorded healthy — "
        "indistinguishable from a legitimately empty feed, hiding a real breakage."
    )
    assert source.last_error_info, "A broken feed must leave a diagnosable error message."


def test_legitimately_empty_well_formed_feed_is_still_healthy(db_session):
    """
    Neighboring/contrast case: a genuinely well-formed feed with zero
    current entries (the common, correct case — e.g. a low-traffic blog
    with nothing published this cycle) must still be recorded healthy.
    The fix must distinguish "not a feed" from "a feed with nothing in
    it right now", not conflate them in the other direction.
    """
    empty_feed = '<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet Blog</title></channel></rss>'
    source = _run_cycle_with_response_text(db_session, empty_feed)

    assert source.health_status == "healthy", (
        "A genuinely well-formed, legitimately empty feed must still be recorded healthy."
    )


def test_truncated_malformed_xml_that_is_still_feed_shaped_is_not_flagged_as_not_a_feed(db_session):
    """
    Neighboring attack on the fix itself: a genuinely malformed XML feed
    (feedparser's own bozo=True case — truncated mid-entry) still contains
    a real <rss> root tag. looks_like_feed() must return True for it, so
    this new check does not fire a SECOND, redundant/misleading "not a
    feed" error on top of whatever parse_rss_feed already salvaged —
    that failure mode (if any) is handled by the pre-existing per-entry
    exception isolation in parse_rss_feed, not this new check.
    """
    truncated_but_feed_shaped = '<?xml version="1.0"?><rss version="2.0"><channel><item><title>Truncated mid'
    source = _run_cycle_with_response_text(db_session, truncated_but_feed_shaped)

    # Whatever parse_rss_feed salvages (likely nothing usable from a title
    # with no closing tag/link) — the point of THIS test is narrower: the
    # error, if any, must not be the new "does not look like a feed"
    # message, since it demonstrably does look like one.
    if source.last_error_info:
        assert "does not look like" not in source.last_error_info, (
            f"A feed-shaped (if malformed) payload was misclassified as 'not a feed': "
            f"{source.last_error_info}"
        )


def test_feed_with_large_preamble_before_root_tag_is_still_detected(db_session):
    """
    Neighboring attack: a real feed can have XML declarations, stylesheet
    processing instructions, DOCTYPE, and comments before its root
    element. Confirms looks_like_feed()'s bounded 4096-char scan window
    is generous enough for a realistic (if unusually verbose) preamble,
    not just a minimal one — guards against this fix introducing a NEW
    false positive (a real feed wrongly flagged as broken) for feeds with
    more preamble than the tests above exercise.
    """
    verbose_preamble = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<?xml-stylesheet type="text/xsl" href="/feed-style.xsl"?>\n'
        + ("<!-- padding comment to simulate a verbose preamble -->\n" * 20)
        + '<rss version="2.0"><channel><title>Verbose Preamble Blog</title>'
        '<item><title>Real Article</title><link>https://example.com/a</link>'
        '<description>Enough content here to pass the minimum length gate for a real article body.</description>'
        "</item></channel></rss>"
    )
    assert len(verbose_preamble) < 4096, "test setup: preamble must stay within the scan window to be meaningful"
    source = _run_cycle_with_response_text(db_session, verbose_preamble)

    assert source.health_status == "healthy", (
        "A real feed with a verbose (but realistic) preamble before its root tag was "
        "incorrectly flagged as not looking like a feed."
    )
