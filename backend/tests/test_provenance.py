"""Not-discovered provenance is unknown, not a confirmed absence."""
from app.core.provenance import Provenance, ProvenanceFacts, classify_provenance


def test_there_is_no_confirmed_absent_state():
    values = {item.value for item in Provenance}
    assert "CONFIRMED_ABSENT" not in values
    assert "PRIMARY_SOURCE_DOES_NOT_EXIST" not in values
    assert Provenance.PRIMARY_SOURCE_NOT_DISCOVERED.value == "PRIMARY_SOURCE_NOT_DISCOVERED"


def test_not_discovered_stays_distinct_from_absence_and_from_other_failures():
    result = classify_provenance(ProvenanceFacts(best_tier="secondary"))
    assert result == Provenance.PRIMARY_SOURCE_NOT_DISCOVERED
    assert result != Provenance.LEGITIMATELY_SECONDARY
    assert result != Provenance.FEED_MISSING
    assert result != Provenance.PRIMARY_SOURCE_BLOCKED


def test_blocked_feed_is_not_treated_as_a_missing_or_absent_source():
    result = classify_provenance(ProvenanceFacts(best_tier="secondary", feed_status="403"))
    assert result == Provenance.PRIMARY_SOURCE_BLOCKED


def test_missing_feed_is_not_a_blocked_site():
    result = classify_provenance(ProvenanceFacts(best_tier="secondary", feed_status="404"))
    assert result == Provenance.FEED_MISSING


def test_discovered_url_without_publisher_is_not_stored_origin():
    result = classify_provenance(ProvenanceFacts(
        best_tier="community",
        article_host="examplelab.com",
        ingest_is_aggregator=True,
    ))
    assert result == Provenance.DISCOVERED_BUT_NOT_STORED


def test_publisher_evidence_that_was_not_persisted_is_a_resolution_failure():
    result = classify_provenance(ProvenanceFacts(
        best_tier="community",
        article_host="examplelab.com",
        ingest_is_aggregator=True,
        publisher_name="Example Lab",
    ))
    assert result == Provenance.PRIMARY_SOURCE_RESOLUTION_FAILED


def test_investigation_without_an_official_url_is_legitimately_secondary():
    result = classify_provenance(ProvenanceFacts(
        best_tier="secondary",
        legitimately_secondary=True,
    ))
    assert result == Provenance.LEGITIMATELY_SECONDARY


def test_stored_official_match_is_primary():
    result = classify_provenance(ProvenanceFacts(
        best_tier="community",
        official_source_name="Example Lab",
        official_host_matches_primary=True,
    ))
    assert result == Provenance.STORED_PRIMARY
