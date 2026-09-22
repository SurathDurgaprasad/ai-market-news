import pytest
from app.core.origin import resolve_originating_source, same_registrable_host, extract_publisher_from_html

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


def test_lookalike_domain_under_shared_public_suffix_is_not_same_site():
    """
    CONFIRMED DEFECT (fixed this pass, docs/RED_TEAM_REPORT.md
    ORIGIN-PSL-01): same_registrable_host() used a naive last-2-labels
    comparison with no public-suffix awareness. bbc.co.uk and evil.co.uk
    both reduce to ("co", "uk") under that scheme and compared equal,
    even though `.co.uk` is a public suffix (like `.com`), not a
    registrable domain, and these are two unrelated sites. Reproduced
    directly against the pre-fix function before patching.

    Practical impact via the only call site (resolve_originating_source's
    different_site check): this biased toward treating unrelated .co.uk
    (and other multi-label-suffix) publishers as "the same site" as the
    aggregator's own host, which suppressed legitimate promotion — a
    fail-closed/conservative failure, not a trust-escalation one, but a
    real loss of provenance for a large class of real-world publishers
    (any co.uk/com.au/co.jp/... outlet reached via an aggregator).
    """
    assert same_registrable_host("bbc.co.uk", "evil.co.uk") is False
    assert same_registrable_host("theguardian.com", "example.com") is False
    # subdomain vs its own registrable domain under a multi-label suffix
    # must still be recognized as the same site
    assert same_registrable_host("news.bbc.co.uk", "bbc.co.uk") is True


def test_aggregator_to_lookalike_couk_publisher_still_promotes_correctly():
    """
    End-to-end through resolve_originating_source: an aggregator item
    linking to a genuine .co.uk publisher, with real page evidence, must
    be promoted — before the ORIGIN-PSL-01 fix this failed because
    same_registrable_host("news.ycombinator.com", "bbc.co.uk") collapsed
    incorrectly via the co.uk suffix (unrelated to ycombinator.com, but
    proves the bug wasn't confined to same-suffix pairs — any host
    landing on a listed multi-label suffix was affected).
    """
    res = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com",
        article_url="https://www.bbc.co.uk/news/technology-123",
        publisher_name="BBC News",
    )
    assert res.used_official is True
    assert res.display_name == "BBC News"


def test_jsonld_publisher_with_nested_logo_object_is_extracted():
    """
    CONFIRMED DEFECT (fixed this pass, docs/RED_TEAM_REPORT.md
    ORIGIN-PSL-01): _JSONLD_PUBLISHER's regex used `[^}]*` between
    "publisher": { and "name", which stops at the FIRST closing brace.
    Real-world schema.org Organization/Publisher JSON-LD very commonly
    nests a "logo": {...} object before "name" — that nested object's
    own closing brace terminated the match early, so the regex found
    nothing and genuine, present publisher evidence was silently missed.
    Reproduced directly against the pre-fix regex before patching.
    """
    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"NewsArticle",'
        '"publisher":{"@type":"Organization",'
        '"logo":{"@type":"ImageObject","url":"https://example.com/logo.png"},'
        '"name":"Real Publisher Corp"}}'
        "</script>"
    )
    assert extract_publisher_from_html(html) == "Real Publisher Corp"


def test_jsonld_publisher_name_before_nested_logo_still_extracted():
    # Neighboring case: "name" appearing before the nested object must
    # keep working (regression check against the widened pattern).
    html = (
        '{"publisher":{"@type":"Organization","name":"Real Publisher Corp",'
        '"logo":{"@type":"ImageObject","url":"https://example.com/logo.png"}}}'
    )
    assert extract_publisher_from_html(html) == "Real Publisher Corp"


def test_og_site_name_still_wins_over_conflicting_jsonld_publisher():
    """
    Documents existing, deliberate precedence (not a new fix): when both
    og:site_name and a JSON-LD publisher name are present and disagree,
    og:site_name wins unconditionally because extract_publisher_from_html
    checks it first and JSON-LD is only consulted if og:site_name is
    entirely absent. This is the same class of tradeoff already accepted
    in test_origin_aggregator_to_official_with_fake_og_site_name (trusting
    page-self-reported metadata) — locking in the actual precedence rule
    here so it's an explicit, tested contract rather than incidental code
    order.
    """
    html = (
        '<meta property="og:site_name" content="Attacker Impersonation Site">'
        '<script type="application/ld+json">'
        '{"publisher":{"name":"Real Publisher Corp"}}'
        "</script>"
    )
    assert extract_publisher_from_html(html) == "Attacker Impersonation Site"
