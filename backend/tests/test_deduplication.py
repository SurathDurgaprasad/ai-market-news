from app.core.deduplication import (
    normalize_url,
    generate_content_hash,
    is_duplicate_title,
    verify_citations,
    titles_suggest_different_events,
    titles_are_safe_lexical_match,
    titles_have_contrasting_claims,
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


def test_hyphenated_and_fused_product_codes_are_not_a_false_conflict():
    """
    CONFIRMED DEFECT (fixed this pass, docs/RED_TEAM_REPORT.md
    DEDUP-MARKER-NOTATION-01): extract_event_markers extracted a bare
    "num:5" marker for the hyphenated "GPT-5" but a "code:gpt5" marker for
    the fused "GPT5" — disjoint sets for the same product, so two outlets
    reporting the identical GPT-5 story with different hyphenation
    registered as a marker CONFLICT. Reproduced directly before fixing:
    extract_event_markers("GPT-5 released") == {"num:5"} while
    extract_event_markers("GPT5 released") == {"code:gpt5"}.

    Impact was fail-closed (an unnecessary LLM round-trip for a same-story
    near-duplicate, not a false merge) but real and previously untested.
    """
    assert not titles_suggest_different_events(
        "GPT-5 released today", "GPT5 released today"
    )
    assert titles_are_safe_lexical_match(
        "OpenAI GPT-5 Model Available Now", "OpenAI GPT5 Model Available Now"
    )
    # space-separated form must also normalize the same way
    assert not titles_suggest_different_events(
        "GPT 5 released today", "GPT5 released today"
    )


def test_contrasting_claims_prevent_false_fast_path_merge():
    """
    CONFIRMED DEFECT (fixed this pass, docs/RED_TEAM_REPORT.md
    DEDUP-CONTRADICTION-01): the marker-conflict check only detects
    DISAGREEING numeric/code markers, not semantic contradiction in the
    surrounding prose. Two articles making OPPOSITE factual claims about
    the same product, phrased with a long shared word sequence and only
    the claim itself differing, passed every existing safety gate
    (Jaccard >= 0.85, no marker conflict, markers non-empty and
    intersecting) and would have fast-path merged into the same event
    with NO LLM verification at all — the most damaging failure mode
    explicitly flagged for this attack pass. Reproduced directly against
    the pre-fix function before patching.
    """
    t1 = (
        "NVIDIA CEO Jensen Huang Says H200 Chip Production Is On Track "
        "For Full Capacity This Quarter"
    )
    t2 = (
        "NVIDIA CEO Jensen Huang Says H200 Chip Production Is Behind "
        "For Full Capacity This Quarter"
    )
    assert titles_have_contrasting_claims(t1, t2)
    assert titles_are_safe_lexical_match(t1, t2) is False


def test_negation_asymmetry_prevents_false_fast_path_merge():
    """
    Second, independent reproduction of DEDUP-CONTRADICTION-01: a bare
    negation word ("not") in only one of two otherwise near-identical,
    same-product-code titles also bypassed every existing safety gate
    before this fix.
    """
    t1 = (
        "NVIDIA Says H200 Chip Production Delays Will Not Affect This "
        "Quarter Enterprise Shipments"
    )
    t2 = (
        "NVIDIA Says H200 Chip Production Delays Will Affect This "
        "Quarter Enterprise Shipments"
    )
    assert titles_have_contrasting_claims(t1, t2)
    assert titles_are_safe_lexical_match(t1, t2) is False


def test_contrasting_claims_check_does_not_flag_agreeing_titles():
    # Neighboring/contrast case: the new check must not fire on titles
    # that merely share vocabulary from the same contrast group without
    # actually disagreeing (both use "confirmed").
    assert not titles_have_contrasting_claims(
        "OpenAI confirms GPT-5 pricing update", "OpenAI confirmed GPT-5 pricing update"
    )
    assert titles_are_safe_lexical_match(
        "OpenAI GPT-5 Model Available Now", "OpenAI GPT-5 Model Available"
    )


def test_hyphen_normalization_does_not_weaken_genuine_conflicts():
    """
    Neighboring/contrast case for the DEDUP-MARKER-NOTATION-01 fix: the
    normalization must not make genuinely different products/magnitudes
    look compatible. Re-asserts the pre-existing conflict cases still
    hold after widening marker extraction.
    """
    assert titles_suggest_different_events("GPT-5 released", "GPT-4 released")
    assert titles_suggest_different_events(
        "NVIDIA Announces H200 GPU Availability",
        "NVIDIA Announces B200 GPU Availability",
    )
    assert titles_suggest_different_events(
        "OpenAI raises $6.6 billion", "OpenAI raises $6.6 million"
    )
