"""
Article text is the post, not the page around it. Found live on the Hugging
Face blog: comment-thread JSON in a data attribute leaked into the stored
body because tags were stripped at the first ">" even inside quoted values,
and <main> also wrapped upvotes, "More Articles" and comments.
"""
import time

from app.core.article_body import _prefer_main_html
from app.core.deduplication import is_immaterial_change
from app.core.parser import sanitize_html

PAGE = (
    "<html><body><main>"
    "<div class='header'>Upvote 72 +66 Follow</div>"
    '<div class="blog-content prose mx-auto">'
    "<h1>Tokenizers v1</h1><div><p>Tokenizers v1 is 3x to 30x faster than v0.23.</p>"
    "<p>It keeps the same token IDs for every supported model family.</p></div>"
    "</div>"
    "<div class='more'>More Articles: Pruning LLMs 25 September 21</div>"
    '<div class="SVELTE_HYDRATER" data-props="{&quot;comments&quot;:[{&quot;html&quot;:&quot;<p>Amazing</p>&quot;,'
    '&quot;followerCount&quot;:4172,&quot;isUserFollowing&quot;:false}]}"></div>'
    "</main></body></html>"
)


def test_quoted_attribute_values_never_leak_into_text():
    text = sanitize_html('<p data-props="{&quot;x&quot;:&quot;<p>Amazing</p>&quot;}">Real text</p>')
    assert text == "Real text"
    whole = sanitize_html(PAGE)
    assert "isUserFollowing" not in whole and "followerCount" not in whole


def test_post_body_container_is_preferred_over_main():
    text = sanitize_html(_prefer_main_html(PAGE))
    assert "3x to 30x faster" in text and "same token IDs" in text
    for chrome in ("Upvote", "More Articles", "Amazing", "Follow"):
        assert chrome not in text


def test_ordinary_text_is_unchanged():
    assert sanitize_html("a < b and it's <b>fine</b> <img alt=it's src=x>ok") == "a ＜ b and it's fine ok"


def test_hostile_markup_is_linear():
    for hostile in (
        ("<a href='x " + "y" * 50) * 20000,
        ('<a b="c ' + "z" * 40) * 25000,
        "<p>" + "<" * 500000,
        ("<a b='" + "q'" * 3) * 60000,
    ):
        started = time.perf_counter()
        sanitize_html(hostile)
        assert time.perf_counter() - started < 3


def test_cleaner_extraction_of_an_unchanged_post_is_not_a_new_version():
    old = sanitize_html(PAGE)  # what the previous extraction stored
    new = sanitize_html(_prefer_main_html(PAGE.replace("Upvote 72", "Upvote 80")))
    assert is_immaterial_change(old, new)
    assert not is_immaterial_change(old, new + " Update: v1 final is delayed to October.")


def test_a_different_cut_point_of_a_capped_body_is_not_an_edit():
    from app.core.article_body import MAX_CONTENT_CHARS

    post = ("Tokenizers v1 keeps the same token IDs for every model family. " * 1000)
    old = post[:MAX_CONTENT_CHARS]
    new = ("Upvote 72 " + post)[:MAX_CONTENT_CHARS]
    assert is_immaterial_change(old, new)
    # An edit in the middle of a capped body is still material.
    middle = MAX_CONTENT_CHARS // 2
    edited = old[:middle] + " Update: final release delayed to October. " + old[middle:]
    assert not is_immaterial_change(old, edited[:MAX_CONTENT_CHARS])


def test_rotating_promo_block_is_not_article_text():
    """Microsoft Research rotates this block per request; kept, every poll looked like an edit."""
    from app.core.article_body import _prefer_main_html
    from app.core.parser import sanitize_html

    def page(promo: str) -> str:
        return (
            '<html><body><div class="entry-content">'
            "<p>CARE-X is a research model that unifies chest X-ray interpretation tasks.</p>"
            '<div class="border-top msr-promo text-center" data-bi-aN="promo">'
            f'<p class="msr-promo__label"><span>{promo}</span></p>'
            '<div class="row"><div class="col">Listen now</div></div></div>'
            "<p>It combines generative and discriminative capabilities.</p>"
            "</div></body></html>"
        )

    first = sanitize_html(_prefer_main_html(page("PODCAST SERIES")))
    second = sanitize_html(_prefer_main_html(page("Microsoft Research at BUILD 2026")))
    assert first == second
    assert "Listen now" not in first
    assert "generative and discriminative" in first


def test_promotion_words_in_ordinary_classes_are_kept():
    from app.core.parser import drop_promo_blocks as _drop_promo_blocks

    html = '<div class="promotional-offer">keep a</div><div class="promotion">keep b</div>'
    assert _drop_promo_blocks(html) == html


def test_feed_body_promo_is_dropped_too():
    """The Microsoft Research RSS body carries the same rotating promo block."""
    from app.core.parser import parse_rss_feed

    def feed(promo: str) -> str:
        body = (
            "<p>Orchard is an open framework for scalable agentic AI.</p>"
            f'<div class="msr-promo"><p><span>{promo}</span></p><div><a href="#">Learn more</a></div></div>'
            "<p>It runs agents across many machines.</p>"
        )
        return (
            '<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            "<channel><title>MSR</title><item><title>Orchard</title><link>https://ms.example/orchard</link>"
            f"<content:encoded><![CDATA[{body}]]></content:encoded></item></channel></rss>"
        )

    first = parse_rss_feed(feed("PODCAST SERIES"))[0].content
    second = parse_rss_feed(feed("Microsoft Research at BUILD 2026"))[0].content
    assert first == second
    assert "Learn more" not in first
    assert "runs agents across many machines" in first
