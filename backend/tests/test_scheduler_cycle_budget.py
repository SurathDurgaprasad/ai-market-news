"""
Phase 1B, second attack pass, Area E (scheduler whole-cycle budget).

Explicit instruction for this area: do NOT immediately add a timeout —
first measure the actual behavior. This file measures, rather than
assumes, what a single pathological (slow) source does to the rest of an
ingestion cycle, using the real run_ingestion_cycle() with only the
network fetch faked (no timeout/architecture change made here).

Confirmed by direct code reading of app/core/scheduler.py before writing
this: the per-source loop (`for source_id, ... in source_targets:`) is a
single, strictly sequential Python for-loop with no per-source timeout,
no per-cycle deadline, and no concurrency — each due source's fetch +
parse + per-article LLM classification/summarization runs to completion
before the next source is even started. APScheduler's own
max_instances=1/coalesce (already verified in Phase 1A) prevents two
cycles from running concurrently, but says nothing about how long a
single cycle itself may run.
"""
import time
from unittest.mock import patch

from app.core.scheduler import IngestionScheduler
from app.models.source import Source


_EMPTY_FEED = '<?xml version="1.0"?><rss version="2.0"><channel><title>{name}</title></channel></rss>'


def test_one_slow_source_delays_later_sources_in_the_same_cycle(db_session):
    """
    Measures (does not assume): with a slow source A due alongside fast
    sources B and C, does the cycle process B/C only after A's slow fetch
    completes, and does the whole cycle's wall-clock duration reflect A's
    delay being fully absorbed rather than bounded/skipped?
    """
    # The db_session fixture pre-creates its own enabled "Test Source" —
    # disable it so only the three sources under test are due this cycle.
    fixture_source = db_session.query(Source).filter(Source.name == "Test Source").first()
    if fixture_source:
        fixture_source.enabled = False

    sources = []
    for name, tier in (("Slow-A", "high"), ("Fast-B", "high"), ("Fast-C", "high")):
        s = Source(name=name, url=f"https://{name.lower()}.example.com/rss", enabled=True, type="rss", polling_tier=tier)
        db_session.add(s)
        sources.append(s)
    db_session.commit()
    source_ids = {s.name: s.id for s in sources}

    SLOW_SECONDS = 1.0  # deliberately short so the test itself stays fast; the
    # measurement is about RELATIVE ordering/duration, not absolute magnitude.
    fetch_started_at: dict[str, float] = {}
    fetch_finished_at: dict[str, float] = {}

    def fake_fetch(url, *args, **kwargs):
        name = url.split("//")[1].split(".")[0]
        fetch_started_at[name] = time.monotonic()
        if "slow-a" in url:
            time.sleep(SLOW_SECONDS)
        resp = type("Resp", (), {"text": _EMPTY_FEED.format(name=name)})()
        fetch_finished_at[name] = time.monotonic()
        return resp

    db_session.close = lambda: None  # keep the same session alive across the whole cycle, like the fixture's db_session

    scheduler = IngestionScheduler()
    cycle_start = time.monotonic()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        with patch("app.core.fetcher.fetch_url", side_effect=fake_fetch):
            scheduler.run_ingestion_cycle()
    cycle_duration = time.monotonic() - cycle_start

    assert set(fetch_started_at.keys()) == {"slow-a", "fast-b", "fast-c"}, (
        "all three due sources must have been attempted within the single cycle "
        f"(got {sorted(fetch_started_at.keys())}) — confirms max_instances=1/coalesce "
        "does not cause a slow source to make OTHER sources silently skipped this tick"
    )

    # MEASUREMENT 1: fast-b and fast-c were not even attempted until slow-a's
    # fetch had already finished — proving strict sequential ordering with no
    # concurrency, exactly as read in the code.
    assert fetch_started_at["fast-b"] >= fetch_finished_at["slow-a"], (
        "fast-b's fetch started before slow-a's fetch finished — this would mean "
        "the cycle is NOT strictly sequential (contradicts the code reading)"
    )
    assert fetch_started_at["fast-c"] >= fetch_finished_at["slow-a"], (
        "fast-c's fetch started before slow-a's fetch finished — this would mean "
        "the cycle is NOT strictly sequential (contradicts the code reading)"
    )

    # MEASUREMENT 2: the slow source's delay is fully absorbed into the total
    # cycle duration — nothing bounds or skips it. This is the concrete,
    # measured confirmation of the architectural characteristic already
    # flagged (unmeasured) in docs/ENGINEERING_STATUS.md's Phase 1A section.
    assert cycle_duration >= SLOW_SECONDS, (
        f"cycle completed in {cycle_duration:.2f}s, faster than the slow source's own "
        f"{SLOW_SECONDS}s fetch delay — expected the delay to be fully absorbed, "
        "not bounded by any timeout (none exists in the current architecture)"
    )

    # All three sources must still have been recorded healthy — a slow but
    # eventually-successful fetch is not a failure.
    db_session.expire_all()
    for name in ("Slow-A", "Fast-B", "Fast-C"):
        refreshed = db_session.query(Source).filter(Source.id == source_ids[name]).first()
        assert refreshed.health_status == "healthy", f"{name} was not recorded healthy after a slow-but-successful fetch"


def test_single_source_retry_amplification_is_bounded_by_fetch_urls_own_retry_budget(db_session):
    """
    Measures whether a single persistently-erroring source's retry
    amplification (fetch_url's own tenacity retry: stop_after_attempt(4),
    wait_exponential(min=2, max=10)) is bounded, or whether the scheduler
    adds ANOTHER layer of retries on top of it within one cycle (which
    would compound the delay a slow/failing source imposes on the rest of
    the cycle). Uses the real fetch_url (only the underlying transport is
    faked) so the real retry decorator actually runs.
    """
    import httpx

    # Disable the db_session fixture's own default source so only the one
    # under test is due this cycle.
    fixture_source = db_session.query(Source).filter(Source.name == "Test Source").first()
    if fixture_source:
        fixture_source.enabled = False

    source = Source(
        name="Erroring", url="https://erroring.example.com/rss",
        enabled=True, type="rss", polling_tier="high",
    )
    db_session.add(source)
    db_session.commit()
    source_id = source.id
    db_session.close = lambda: None

    call_count = {"n": 0}

    class _AlwaysServerErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(503, headers={"content-type": "text/plain"}, content=b"Service Unavailable")

    transport = _AlwaysServerErrorTransport()
    real_httpx_client = httpx.Client  # capture before patching — `app.core.fetcher.httpx`
    # IS the real httpx module object, so patching httpx.Client through it patches
    # httpx.Client globally; referencing httpx.Client again inside the side_effect
    # would recurse into the patch itself.

    scheduler = IngestionScheduler()
    with patch("app.core.scheduler.SessionLocal", return_value=db_session):
        # Only the transport is faked; app.core.fetcher.fetch_url and its
        # real @retry decorator run unmodified — patch what fetch_url
        # itself uses internally (httpx.Client, pin_host), not fetch_url.
        # A fresh Client per call: fetch_url's own `with httpx.Client(...)`
        # closes the client at the end of each call, so a single shared
        # instance would raise on the second retry attempt.
        with patch(
            "app.core.fetcher.httpx.Client",
            side_effect=lambda *a, **kw: real_httpx_client(transport=transport, follow_redirects=False),
        ):
            with patch("app.core.fetcher.pin_host"):
                scheduler.run_ingestion_cycle()

    # fetch_url's own @retry allows at most 4 attempts (stop_after_attempt(4)).
    # If the scheduler wrapped ANOTHER retry layer around the whole
    # fetch+parse call, call_count would be a multiple of 4, not exactly 4 —
    # this is the concrete, measured check for compounding retry amplification.
    assert call_count["n"] == 4, (
        f"expected exactly fetch_url's own retry budget (4 attempts), got {call_count['n']} — "
        "a higher multiple would indicate the scheduler adds its own retry layer on top, "
        "compounding a single failing source's delay within one cycle"
    )

    db_session.expire_all()
    refreshed = db_session.query(Source).filter(Source.id == source_id).first()
    assert refreshed.health_status == "failing"
