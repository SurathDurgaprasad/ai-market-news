from app.core.origin import resolve_originating_source, extract_publisher_from_html
from app.core.entities import dedupe_entities, select_primary_entities


def test_official_blog_stays_ingest_source():
    origin = resolve_originating_source(
        ingest_name="NVIDIA AI Blog",
        ingest_url="https://blogs.nvidia.com/feed",
        article_url="https://blogs.nvidia.com/blog/nemotron",
        publisher_name="NVIDIA AI Blog",
    )
    assert origin.used_official is False
    assert origin.display_name == "NVIDIA AI Blog"


def test_rss_aggregator_to_vendor_article_uses_page_publisher():
    origin = resolve_originating_source(
        ingest_name="Google News",
        ingest_url="https://news.google.com/rss",
        article_url="https://blogs.nvidia.com/blog/rubin",
        publisher_name="NVIDIA Blog",
    )
    assert origin.used_official is True
    assert origin.display_name == "NVIDIA Blog"
    assert origin.ingest_name == "Google News"


def test_hacker_news_to_vendor_article_uses_page_publisher():
    origin = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com/rss",
        article_url="https://www.hacktron.ai/blog/hacking-openai",
        publisher_name="Hacktron",
    )
    assert origin.used_official is True
    assert origin.display_name == "Hacktron"
    assert origin.ingest_name == "Hacker News"
    assert "hacktron.ai" in origin.official_url


def test_hacker_news_without_publisher_evidence_does_not_guess_from_domain():
    origin = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com/rss",
        article_url="https://www.hacktron.ai/blog/hacking-openai",
        publisher_name=None,
    )
    assert origin.used_official is False
    assert origin.display_name == "Hacker News"


def test_aggregator_discussion_stays_hacker_news():
    origin = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com/rss",
        article_url="https://news.ycombinator.com/item?id=123",
        publisher_name="Hacker News",
    )
    assert origin.used_official is False
    assert origin.display_name == "Hacker News"


def test_source_unavailable():
    origin = resolve_originating_source(
        ingest_name=None,
        ingest_url=None,
        article_url=None,
        publisher_name=None,
    )
    assert origin.display_name is None
    assert origin.used_official is False


def test_ambiguous_origin_multiple_outlets_without_publisher():
    origin = resolve_originating_source(
        ingest_name="TechCrunch",
        ingest_url="https://techcrunch.com/feed",
        article_url="https://techcrunch.com/2026/openai",
        publisher_name=None,
    )
    assert origin.display_name == "TechCrunch"


def test_title_suffix_needs_page_corroboration_and_then_resolves():
    from app.core.origin import evidence_tier_for_origin

    bare = "<title>Introducing a model \\ Example Lab</title>"
    assert extract_publisher_from_html(bare) == ""
    html = """
    <title>Introducing a model \\ Example Lab</title>
    <meta name="twitter:site" content="@ExampleLabAI">
    <meta property="og:image:alt" content="Example Lab logo">
    """
    assert extract_publisher_from_html(html) == "Example Lab"
    origin = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com/rss",
        article_url="https://www.examplelab.com/model",
        publisher_name="Example Lab",
    )
    assert origin.used_official is True
    assert origin.official_name == "Example Lab"
    assert origin.official_url == "https://www.examplelab.com/model"
    assert evidence_tier_for_origin(origin, {"examplelab.com"}) == "primary"


def test_preprint_origin_is_research_when_the_publisher_is_on_the_page():
    from app.core.origin import evidence_tier_for_origin

    html = '<meta property="og:site_name" content="arXiv.org">'
    assert extract_publisher_from_html(html) == "arXiv.org"
    origin = resolve_originating_source(
        ingest_name="Hacker News",
        ingest_url="https://news.ycombinator.com/rss",
        article_url="https://arxiv.org/abs/0000.00000",
        publisher_name="arXiv.org",
    )
    assert origin.used_official is True
    assert evidence_tier_for_origin(origin, set()) == "research"
    assert evidence_tier_for_origin(origin, set()) != "primary"


def test_extract_publisher_from_html_og_and_jsonld():
    html = '<meta property="og:site_name" content="Hacktron">'
    assert extract_publisher_from_html(html) == "Hacktron"
    html = '{"publisher": {"name": "Hugging Face Blog", "url": "https://huggingface.co"}}'
    assert "Hugging Face" in extract_publisher_from_html(html)


def test_entity_dedupe_and_primary_vs_mentioned():
    primary, mentioned = select_primary_entities(
        all_entities=[
            "Sentence Transformers",
            "Jina AI",
            "Jina AI",
            "jina ai",
            "Hugging Face",
            "GPU",
            "FIFO",
        ],
        headline="Sentence Transformers v6.0 Adds MultiVectorEncoder",
        summary="Sentence Transformers released version 6.0.",
        limit=6,
    )
    assert primary[0] == "Sentence Transformers"
    assert len([e for e in primary + mentioned if e.lower() == "jina ai"]) == 1
    assert "GPU" not in primary + mentioned
    assert "FIFO" not in primary + mentioned


def test_explicit_primary_entities_win():
    primary, mentioned = select_primary_entities(
        primary=["IBM", "Granite 4.2"],
        all_entities=["IBM", "Granite 4.2", "vLLM", "SGLang", "SGLang"],
        headline="Granite 4.2 Released",
        limit=6,
    )
    assert primary == ["IBM", "Granite 4.2"]
    assert mentioned[0] == "vLLM"
    assert mentioned.count("SGLang") == 1


def test_oversized_primary_list_is_ranked_not_blindly_sliced():
    primary, mentioned = select_primary_entities(
        primary=[
            "vLLM",
            "SGLang",
            "llama.cpp",
            "CUDA",
            "Thinking Machines Lab",
            "Hugging Face",
            "NVIDIA",
            "PyTorch",
        ],
        headline="Thinking Machines Releases Inkling-Small",
        summary="Thinking Machines Lab released Inkling-Small on Hugging Face.",
        limit=6,
    )
    assert "Thinking Machines Lab" in primary
    assert len(primary) <= 6
    assert "PyTorch" in mentioned or "PyTorch" not in primary[:2]


def test_dedupe_entities_aliases_case():
    assert dedupe_entities(["OpenAI", "openai", " OpenAI "]) == ["OpenAI"]
