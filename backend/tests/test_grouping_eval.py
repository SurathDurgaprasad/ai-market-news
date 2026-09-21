"""
Grouping evaluation on controlled fixtures.

This does not claim global production recall. The live corpus is almost
entirely single-outlet Hugging Face posts, so missed-merge rate cannot be
measured there. False merges are worse than missed merges.
"""
from app.core.deduplication import (
    titles_are_safe_lexical_match,
    titles_suggest_different_events,
)
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.models.source import Source
from app.models.event import Event, EventArticle


def test_same_event_different_wording_merges_via_llm_trigger(db_session):
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    source = db_session.query(Source).first()
    first = pipeline.process_article(
        ArticleData(
            title="OpenAI Releases GPT-5",
            url="https://openai.com/blog/gpt-5",
            content="Today we are releasing GPT-5, our most capable model yet. It features expanded reasoning capabilities.",
        ),
        source.id,
    )
    second = pipeline.process_article(
        ArticleData(
            title="OpenAI launches GPT-5 for developers",
            url="https://techcrunch.com/openai-gpt5",
            content="OpenAI just dropped GPT-5. The new model is highly capable and improves reasoning. duplicate_trigger",
        ),
        source.id,
    )
    assert first is not None and second is not None
    assert first.id == second.id
    links = db_session.query(EventArticle).filter(EventArticle.event_id == first.id).all()
    assert len(links) == 2


def test_same_company_different_events_do_not_merge(db_session):
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    source = db_session.query(Source).first()
    first = pipeline.process_article(
        ArticleData(
            title="OpenAI Releases GPT-5",
            url="https://openai.com/blog/gpt-5",
            content="Today we are releasing GPT-5, our most capable model yet. It features expanded reasoning capabilities.",
        ),
        source.id,
    )
    second = pipeline.process_article(
        ArticleData(
            title="OpenAI announces new board member",
            url="https://openai.com/blog/board",
            content="Today we welcome a new board member. This has nothing to do with GPT-5.",
        ),
        source.id,
    )
    assert first.id != second.id
    assert db_session.query(Event).count() == 2


def test_conflicting_markers_are_not_safe_lexical_matches():
    assert titles_suggest_different_events(
        "NVIDIA Announces H200 GPU Availability",
        "NVIDIA Announces B200 GPU Availability",
    )
    assert not titles_are_safe_lexical_match(
        "NVIDIA Announces H200 GPU Availability",
        "NVIDIA Announces B200 GPU Availability",
    )


def test_unrelated_mentions_of_same_model_are_not_safe_matches():
    assert not titles_are_safe_lexical_match(
        "Researchers evaluate GPT-5 on a new math benchmark",
        "Cloud vendor adds GPT-5 to a marketplace catalog",
    )


def test_same_event_paraphrase_is_not_a_lexical_fast_path():
    """Different wording of the same release must not merge on Jaccard 0.85 alone."""
    assert not titles_are_safe_lexical_match(
        "OpenAI Releases GPT-5",
        "OpenAI launches GPT-5 for developers",
    )


def test_official_announcement_and_news_report_not_lexical():
    assert not titles_are_safe_lexical_match(
        "Introducing Granite 4.2",
        "IBM ships Granite 4.2 dense decoder-only models",
    )


def test_security_incident_and_later_confirmation_not_lexical():
    assert not titles_are_safe_lexical_match(
        "Hacktron reports libheif RCE in OpenAI forum",
        "OpenAI confirms a libheif vulnerability in its forum",
    )


def test_follow_up_availability_is_a_different_event_lexically():
    assert titles_suggest_different_events(
        "OpenAI Releases GPT-5",
        "OpenAI expands GPT-5 API availability",
    ) or not titles_are_safe_lexical_match(
        "OpenAI Releases GPT-5",
        "OpenAI expands GPT-5 API availability",
    )


def test_program_using_model_is_not_same_event_as_model_release():
    """
    Regression for Fairwind/Gemini Flash false merge.
    A program that USES model X is not the same event as the release OF model X.
    The titles are sufficiently different that no fast-path merge should fire.
    """
    a = "Proactive cyber defense for governments and enterprises"
    b = "Introducing Gemini 3.8 Flash and 3.8 Flash Cyber"
    # These must not be a safe lexical match — different topics entirely
    assert not titles_are_safe_lexical_match(a, b)
    # No conflicting markers (both from same company, no overlapping product codes)
    # but they should still be correctly blocked from fast-path merge
    assert not titles_suggest_different_events(a, b) or not titles_are_safe_lexical_match(a, b)


def test_same_family_different_tiers_not_lexical():
    """Gemini 3.8 Live vs Gemini 3.8 Flash are different product tiers, not the same event."""
    a = "Introducing Gemini 3.8 Live and 3.8 Live Extended Thinking"
    b = "Introducing Gemini 3.8 Flash and 3.8 Flash Cyber"
    assert not titles_are_safe_lexical_match(a, b)
