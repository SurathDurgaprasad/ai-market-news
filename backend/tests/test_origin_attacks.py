import pytest
from app.core.origin import resolve_originating_source

def test_origin_aggregator_to_official_with_fake_og_site_name():
    # If ingested from an aggregator (Hacker News) and links to an attacker's site,
    # the attacker can put whatever they want in og:site_name.
    # The system will use it as display_name but keep the attacker's URL.
    res = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com",
        article_url="https://malicious.com/post",
        publisher_name="Google AI Blog" # attacker injected this via og:site_name
    )
    
    # It correctly identifies it's an aggregator passing to a different site
    assert res.used_official is True
    
    # KNOWN LIMITATION: The system trusts the page's self-reported og:site_name.
    # So the official_name becomes "Google AI Blog".
    assert res.official_name == "Google AI Blog"
    # But the URL is safely preserved as the actual destination.
    assert res.official_url == "https://malicious.com/post"

def test_origin_official_to_aggregator():
    # If ingested from an official source, it ignores the article's og:site_name
    # to prevent hijacking of official feeds.
    res = resolve_originating_source(
        ingest_name="Google AI Blog",
        ingest_url="https://blog.google",
        article_url="https://blog.google/post",
        publisher_name="Attacker Hijack Name" # attacker injected this somehow
    )
    
    assert res.used_official is False
    assert res.official_name == "Google AI Blog"
    assert res.display_name == "Google AI Blog"

def test_origin_redirects_and_canonical_mismatch():
    # The system relies on the canonical URL passed to resolve_originating_source.
    res = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com",
        article_url="https://example.com/canonical",
        publisher_name="Example Corp"
    )
    
    assert res.official_url == "https://example.com/canonical"
