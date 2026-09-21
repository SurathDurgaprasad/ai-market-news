from unittest.mock import MagicMock

from app.core.article_body import compose_feed_text, enrich_article, extract_og_image, MIN_CONTENT_CHARS
from app.core.parser import ArticleData
from app.core.pipeline import IntelligencePipeline
from app.models.source import Source


def test_compose_uses_title_when_body_empty():
    text = compose_feed_text("A reasonably long headline about an AI model release today", "")
    assert "reasonably long headline" in text
    assert len(text) >= MIN_CONTENT_CHARS


def test_extract_og_image_rejects_javascript():
    html = '<meta property="og:image" content="javascript:alert(1)">'
    assert extract_og_image(html) == ""


def test_extract_og_image_accepts_https():
    html = '<meta property="og:image" content="https://cdn.example.com/pic.jpg?w=800">'
    assert extract_og_image(html) == "https://cdn.example.com/pic.jpg?w=800"


def test_enrich_does_not_fetch_when_body_is_long():
    called = []

    def fetch(url, timeout=8):
        called.append(url)
        raise AssertionError("must not fetch long bodies")

    content, image, publisher = enrich_article(
        "Title",
        "https://example.com/article",
        "This article body is definitely longer than fifty characters for the gate.",
        None,
        fetch_fn=fetch,
    )
    assert called == []
    assert "definitely longer" in content
    assert image is None
    assert publisher is None


def test_html_to_text_prefers_article_over_nav_chrome():
    html = """<html><body>
      <nav>Docs Product Pricing</nav>
      <article><p>OpenAI released a documented model update with a 200K context window and API access today.</p></article>
      <footer>Subscribe to our newsletter</footer>
    </body></html>"""
    resp = MagicMock()
    resp.content = html.encode("utf-8")
    resp.text = html
    content, _, _ = enrich_article(
        "Short", "https://openai.com/blog/x", "tiny", None,
        fetch_fn=lambda url, timeout=8: resp,
    )
    assert "200K context" in content
    assert "Subscribe to our newsletter" not in content
    assert "Pricing" not in content


def test_cookie_banner_and_paywall_chrome_stripped():
    html = """<html><body>
      <div id="cookie-banner">Accept cookies to continue</div>
      <div class="paywall-modal">Subscribe for $12</div>
      <article><p>OpenAI released a documented model update with a 200K context window and API access today.</p></article>
    </body></html>"""
    resp = MagicMock()
    resp.content = html.encode("utf-8")
    resp.text = html
    content, _, _ = enrich_article(
        "Short", "https://openai.com/blog/x", "tiny", None,
        fetch_fn=lambda url, timeout=8: resp,
    )
    assert "200K context" in content
    assert "Accept cookies" not in content
    assert "Subscribe for $12" not in content


def test_enrich_fetches_short_body_and_strips_html():
    html = """<html><head>
      <meta property="og:image" content="https://cdn.example.com/hero.png">
      <meta property="og:site_name" content="OpenAI">
    </head><body>
      <script>alert(1)</script>
      <p>OpenAI released a documented model update with a 200K context window and API access today.</p>
    </body></html>"""
    resp = MagicMock()
    resp.content = html.encode("utf-8")
    resp.text = html

    content, image, publisher = enrich_article(
        "Short",
        "https://openai.com/blog/x",
        "tiny",
        None,
        fetch_fn=lambda url, timeout=8: resp,
    )
    assert "200K context" in content
    assert "alert" not in content
    assert image == "https://cdn.example.com/hero.png"
    assert publisher == "OpenAI"


def test_enrich_returns_title_fallback_when_fetch_fails():
    def fetch(url, timeout=8):
        raise TimeoutError("nope")

    content, image, publisher = enrich_article(
        "Only A Title Here That Is Long Enough To Pass The Gate After Compose",
        "https://example.com/x",
        "",
        None,
        fetch_fn=fetch,
    )
    assert "Only A Title Here" in content
    assert image is None
    assert publisher is None


def test_pipeline_short_feed_item_ingested_after_page_fetch(db_session):
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    source_id = db_session.query(Source).first().id
    article = ArticleData(
        title="Short HN-style title",
        url="https://openai.com/blog/real-page",
        content="8 chars",
    )
    html = (
        "<html><body><p>"
        "Researchers published a new open-weight model with a 128K context window "
        "and documented tokenizer changes in this article."
        "</p></body></html>"
    )
    resp = MagicMock()
    resp.content = html.encode("utf-8")
    resp.text = html
    event = pipeline.process_article(
        article, source_id, fetch_fn=lambda url, timeout=8: resp
    )
    assert event is not None


def test_pipeline_short_feed_item_rejected_without_fetch_or_long_title(db_session):
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    source_id = db_session.query(Source).first().id
    article = ArticleData(
        title="Tiny",
        url="https://example.com/tiny",
        content="nope",
    )
    event = pipeline.process_article(article, source_id, fetch_fn=None)
    assert event is None
