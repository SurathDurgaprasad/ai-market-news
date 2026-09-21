from app.core.deduplication import (
    normalize_url,
    generate_content_hash,
    is_duplicate_title,
    verify_citations,
    titles_suggest_different_events,
    titles_are_safe_lexical_match,
)

def test_normalize_url():
    url1 = "https://example.com/article?utm_source=twitter"
    url2 = "https://example.com/article/"
    url3 = "https://example.com/article#comments"

    canon1 = normalize_url(url1)
    canon2 = normalize_url(url2)
    canon3 = normalize_url(url3)

    assert canon1 == canon2
    assert canon2 == canon3
    assert canon1 == "https://example.com/article"

def test_normalize_url_rejects_unsafe_schemes():
    """
    Security regression: javascript: / data: / ftp: URLs must be rejected.
    If they reached the database, they could be rendered as XSS vectors in the UI.
    """
    # javascript: — classic XSS vector
    assert normalize_url("javascript:alert(1)") == ""
    # data: — can embed arbitrary content
    assert normalize_url("data:text/html,<script>alert(1)</script>") == ""
    # ftp: — not a valid article source
    assert normalize_url("ftp://example.com/file") == ""
    # Empty / None
    assert normalize_url("") == ""
    assert normalize_url(None) == ""
    # Valid HTTP/HTTPS must still work
    assert normalize_url("https://openai.com/blog/gpt-5") == "https://openai.com/blog/gpt-5"
    assert normalize_url("http://example.com/article?ref=twitter") == "http://example.com/article"

def test_generate_content_hash():
    text1 = "This is some content."
    text2 = "This   is  some \n content."
    
    hash1 = generate_content_hash(text1)
    hash2 = generate_content_hash(text2)
    
    assert hash1 == hash2

def test_is_duplicate_title():
    title1 = "OpenAI Releases GPT-5!"
    title2 = "openai releases gpt5"
    title3 = "OpenAI: Releases GPT-5"
    
    assert is_duplicate_title(title1, title2)
    assert is_duplicate_title(title1, title3)
    assert not is_duplicate_title(title1, "Google Releases Gemini 2")

def test_verify_citations():
    content = "The CEO stated 'our revenue increased by 50% this year'. Also, 'the new product is launching tomorrow'."

    # 1. Exact match
    citations_valid = ["our revenue increased by 50% this year", "the new product is launching tomorrow"]
    assert len(verify_citations(content, citations_valid)) == 2

    # 2. Hallucinated match
    citations_mixed = ["our revenue increased by 50% this year", "we are bankrupt"]
    verified = verify_citations(content, citations_mixed)
    assert len(verified) == 1
    assert verified[0] == "our revenue increased by 50% this year"

    # 3. Capitalization differences should still match
    citations_caps = ["Our Revenue Increased by 50% THIS YEAR"]
    assert len(verify_citations(content, citations_caps)) == 1

    # 4. Whitespace differences should still match
    citations_space = ["  our revenue   increased by  50% this year "]
    assert len(verify_citations(content, citations_space)) == 1

    # 5. Short citations (< 15 chars) must be rejected regardless of whether they match
    # "AI" or "the model" are too short to be meaningful evidence
    citations_too_short = ["AI", "the model", "revenue"]
    # "revenue" is 7 chars → rejected. "AI" is 2 → rejected.
    assert len(verify_citations(content, citations_too_short)) == 0


def test_verify_citations_normalizes_unicode_and_html_without_accepting_paraphrase():
    content = (
        "ALTK\u2011Evolve extracts behavioral guidelines from an agent\u2019s own trajectories. "
        "<p>The checkpoint supports a 128k context window.</p>"
    )
    unicode_ok = ["ALTK-Evolve extracts behavioral guidelines from an agent's own trajectories"]
    html_ok = ['The checkpoint supports a 128k context window.']
    paraphrase = ["The system invents a brand new training algorithm for robots"]
    assert len(verify_citations(content, unicode_ok)) == 1
    assert len(verify_citations(content, html_ok)) == 1
    assert verify_citations(content, paraphrase) == []


def test_verify_citations_extracts_quote_objects():
    content = "The checkpoint supports a 128k context window on hosted NIM."
    citations = [{"quote": "The checkpoint supports a 128k context window on hosted NIM."}]
    assert verify_citations(content, citations) == [
        "The checkpoint supports a 128k context window on hosted NIM."
    ]


def test_first_factual_line_skips_empty_bullets():
    from app.core.deduplication import first_factual_line
    assert first_factual_line("- NVIDIA released Nemotron-Mini\n- 128k context") == "NVIDIA released Nemotron-Mini"
    assert first_factual_line("   \n") == ""


def test_first_source_excerpt_skips_chrome_keeps_article_paragraph():
    from app.core.deduplication import first_source_excerpt
    chrome = "jemalloc / jemalloc Public\nNotifications You must be signed in to change notification settings\nFork 1.6k"
    nvidia = (
        "Back to Articles\n"
        "Upvote 80\n"
        "Editor's note: The name of NVIDIA DRIVE Hyperion was changed to NVIDIA Hyperion in September 2026. "
        "All references to the name have been updated in this blog. "
        "NVIDIA founder and CEO Jensen Huang today outlined the Rubin platform, open models, "
        "and autonomous driving as the company's blueprint at CES."
    )
    assert first_source_excerpt(chrome) == ""
    excerpt = first_source_excerpt(nvidia)
    assert excerpt.startswith("NVIDIA founder and CEO Jensen Huang")
    assert "blueprint at CES" in excerpt


def test_verify_citations_rejects_hallucinated_short_strings():
    """Regression: verify_citations must not count short tokens as valid evidence."""
    content = "The GPT-5 model achieves state-of-the-art results on multiple benchmarks."
    # "AI" would always match because content happens to mention AI concepts,
    # but it's too short to be a meaningful citation
    short_hallucinations = ["AI", "model", "GPT"]
    assert len(verify_citations(content, short_hallucinations)) == 0


def test_conflicting_markers_prevent_false_merge():
    assert titles_suggest_different_events(
        "NVIDIA Announces H200 GPU Availability",
        "NVIDIA Announces B200 GPU Availability",
    )
    assert titles_suggest_different_events(
        "OpenAI raises $6.6 billion",
        "OpenAI raises $6.6 million",
    )
    assert titles_suggest_different_events("GPT-5 released", "GPT-4 released")
    # Same product, extra words — not a conflict
    assert not titles_suggest_different_events("GPT-5 released", "GPT-5 API released")


def test_generic_titles_are_not_safe_lexical_matches():
    """Identical generic headlines must NOT fast-path merge."""
    assert not titles_are_safe_lexical_match(
        "OpenAI Announces Update",
        "OpenAI Announces Update",
    )


def test_same_model_titles_are_safe_lexical_matches():
    assert titles_are_safe_lexical_match(
        "OpenAI GPT-5 Model Available Now",
        "OpenAI GPT-5 Model Available",
    )
