from app.core.parser import parse_mock_source, parse_rss_feed, extract_feed_next_url, looks_like_feed
from tests.fixtures.sources import FIXTURES
import datetime
import json

def test_valid_article_parsing():
    parsed = parse_mock_source(json.dumps(FIXTURES["normal_1"]))
    assert parsed.title == "OpenAI Releases GPT-5"
    assert parsed.url == "https://openai.com/blog/gpt-5"

def test_valid_article_preserves_published_at():
    """published_at from mock JSON must be parsed as a timezone-aware datetime."""
    parsed = parse_mock_source(json.dumps(FIXTURES["normal_1"]))
    assert parsed is not None
    assert parsed.published_at is not None
    # Must be timezone-aware (UTC offset = 0)
    assert parsed.published_at.tzinfo is not None
    assert parsed.published_at.year == 2026
    assert parsed.published_at.month == 9
    assert parsed.published_at.day == 17

def test_malformed_json_parsing():
    parsed = parse_mock_source(FIXTURES["malformed_json"])
    assert parsed is None

def test_xss_sanitization():
    parsed = parse_mock_source(json.dumps(FIXTURES["xss_payload"]))
    assert "<script>" not in parsed.title
    assert "alert(1)" not in parsed.title
    assert "<img" not in parsed.content

def test_parser_rejects_javascript_image_url():
    """
    Security: image_url from a malicious RSS entry with javascript: src must be None.
    If it weren't, it could be rendered in <img src="javascript:..."> in the frontend.
    """
    # A mock source with a javascript: image URL
    payload = json.dumps({
        "title": "AI Article",
        "url": "https://legit.example.com/article",
        "content": "Legitimate AI content that is long enough to pass validation checks.",
        "image_url": "javascript:alert(document.cookie)"
    })
    parsed = parse_mock_source(payload)
    assert parsed is not None
    assert parsed.image_url is None


def test_rss_image_url_rejects_javascript():
    """RSS parser must not return javascript: or data: image URLs."""
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Test Feed</title>
    <link>https://test.example.com</link>
    <item>
      <title>Test Article</title>
      <link>https://test.example.com/article</link>
      <description>Content with an injected image: &lt;img src="javascript:alert(1)"&gt; and more text here.</description>
      <media:content url="javascript:alert(1)" medium="image"/>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss_xml)
    assert len(articles) == 1
    # Neither the media:content URL nor the img tag should survive
    assert articles[0].image_url is None or articles[0].image_url.startswith(('http://', 'https://'))
    assert articles[0].image_url is None


def test_rss_media_thumbnail_extraction():
    """Parser must extract media:thumbnail URLs when media:content is absent."""
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Test Feed</title>
    <link>https://test.example.com</link>
    <item>
      <title>AI Thumbnail Test</title>
      <link>https://test.example.com/thumb-article</link>
      <description>Sufficient content for an AI intelligence article to pass validation checks.</description>
      <media:thumbnail url="https://cdn.example.com/thumb.jpg"/>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss_xml)
    assert len(articles) == 1
    assert articles[0].image_url == "https://cdn.example.com/thumb.jpg"


def test_rss_published_at_is_utc():
    """
    Regression: feedparser returns published_parsed as UTC struct_time but the old
    code used time.mktime() which reinterprets it as LOCAL time.  The fix uses
    calendar.timegm() instead, preserving UTC.
    
    This test creates a minimal RSS feed with a known UTC timestamp and verifies
    the parsed datetime matches the expected UTC time.
    """
    # A minimal RSS feed with a known UTC publication time: 2026-09-18T08:00:00Z
    rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://test.example.com</link>
    <item>
      <title>Test Article</title>
      <link>https://test.example.com/article</link>
      <pubDate>Fri, 18 Sep 2026 08:00:00 +0000</pubDate>
      <description>Test content about AI developments.</description>
    </item>
  </channel>
</rss>"""

    articles = parse_rss_feed(rss_xml)
    assert len(articles) == 1
    article = articles[0]
    assert article.published_at is not None
    # Must be timezone-aware UTC
    assert article.published_at.tzinfo is not None
    # Must be 08:00 UTC exactly — not reinterpreted as local time
    assert article.published_at.hour == 8
    assert article.published_at.day == 18
    assert article.published_at.month == 9


def test_atom_feed_and_updated_fallback():
    atom = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom Article About AI</title>
    <link href="https://example.com/atom-article"/>
    <updated>2026-09-18T12:30:00Z</updated>
    <summary>Sufficient Atom summary text about an AI model release for parsing.</summary>
  </entry>
</feed>"""
    articles = parse_rss_feed(atom)
    assert len(articles) == 1
    assert articles[0].url == "https://example.com/atom-article"
    assert articles[0].published_at is not None
    assert articles[0].published_at.hour == 12
    assert articles[0].published_at.minute == 30


def test_malformed_xml_does_not_raise():
    articles = parse_rss_feed("<not-xml oh no <<<")
    assert articles == []


def test_empty_and_none_payload():
    assert parse_rss_feed("") == []
    assert parse_rss_feed("<?xml version='1.0'?><rss><channel></channel></rss>") == []


def test_html_heavy_description_stripped():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>HTML Heavy</title>
      <link>https://example.com/html-heavy</link>
      <description><![CDATA[
        <div><p>First paragraph about GPT-5 release notes.</p>
        <script>alert(1)</script>
        <p>Second paragraph with more technical detail.</p></div>
      ]]></description>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert "<p>" not in articles[0].content
    assert "<script>" not in articles[0].content
    assert "GPT-5" in articles[0].content
    assert "Second paragraph" in articles[0].content


def test_invalid_date_yields_none_published_at():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Bad Date</title>
      <link>https://example.com/bad-date</link>
      <pubDate>not-a-date</pubDate>
      <description>Content long enough that we still ingest the item body text here.</description>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert articles[0].published_at is None


def test_duplicate_entries_in_same_feed_deduped():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Once</title>
      <link>https://example.com/once</link>
      <description>First copy of the article with enough text to count.</description>
    </item>
    <item>
      <title>Once again</title>
      <link>https://example.com/once?utm_source=rss</link>
      <description>Second copy should be dropped by URL canonicalization.</description>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1


def test_feed_entry_cap():
    items = "".join(
        f"<item><title>T{i}</title><link>https://example.com/a{i}</link>"
        f"<description>Body {i} with enough characters for an entry.</description></item>"
        for i in range(150)
    )
    rss = f"""<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 100


def test_enclosure_image_extracted():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Enclosure Image</title>
      <link>https://example.com/enc</link>
      <description>Body text for enclosure image item.</description>
      <enclosure url="https://cdn.example.com/hero.png" type="image/png"/>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert articles[0].image_url == "https://cdn.example.com/hero.png"


def test_one_bad_entry_does_not_drop_feed():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title></title>
      <link></link>
    </item>
    <item>
      <title>Good Item</title>
      <link>https://example.com/good</link>
      <description>This item should survive even if a sibling is empty.</description>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert articles[0].title == "Good Item"


def test_utf8_bom_and_html_entities():
    rss = """\ufeff<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>AT&amp;T AI lab</title>
      <link>https://example.com/entities</link>
      <description>Qwen&apos;s new model is discussed here with enough text.</description>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert "AT&T" in articles[0].title


def test_empty_description_still_parses_title_url():
    rss = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Title Only</title>
      <link>https://example.com/title-only</link>
    </item>
  </channel>
</rss>"""
    articles = parse_rss_feed(rss)
    assert len(articles) == 1
    assert articles[0].content == ""


def test_atom_next_link_is_detected_but_entries_still_parsed():
    atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Paged</title>
  <link rel="next" href="https://example.com/feed?page=2"/>
  <entry>
    <title>Item One</title>
    <link href="https://example.com/one"/>
    <summary>Body text long enough for this entry to be retained in the parse.</summary>
  </entry>
</feed>"""
    articles = parse_rss_feed(atom)
    assert len(articles) == 1
    assert extract_feed_next_url(atom) == "https://example.com/feed?page=2"
    assert extract_feed_next_url("") is None


# INGEST-SILENT-01 (docs/security-findings.md): feedparser's own bozo flag
# does not catch an HTML page served where a feed should be — it parses
# as bozo=False, entries=0, identical to a genuinely empty well-formed
# feed. looks_like_feed() is the separate structural check that closes
# that gap; these are its direct unit tests (the scheduler-level
# reproduction/regression lives in test_scheduler_broken_feed_detection.py).

def test_looks_like_feed_true_for_rss():
    assert looks_like_feed('<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>') is True


def test_looks_like_feed_true_for_atom():
    assert looks_like_feed('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>') is True


def test_looks_like_feed_true_for_rdf():
    assert looks_like_feed('<?xml version="1.0"?><rdf:RDF xmlns:rdf="x"></rdf:RDF>') is True


def test_looks_like_feed_false_for_html_error_page():
    html = "<html><head><title>404 Not Found</title></head><body><h1>404</h1></body></html>"
    assert looks_like_feed(html) is False


def test_looks_like_feed_false_for_empty_or_none():
    assert looks_like_feed("") is False
    assert looks_like_feed(None) is False


def test_looks_like_feed_false_for_plain_text():
    assert looks_like_feed("this is not a feed, just some text") is False


def test_looks_like_feed_handles_bytes_payload():
    assert looks_like_feed(b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>') is True


def test_looks_like_feed_case_insensitive():
    assert looks_like_feed('<?xml version="1.0"?><RSS version="2.0"><channel></channel></RSS>') is True
    assert extract_feed_next_url("<rss></rss>") is None
