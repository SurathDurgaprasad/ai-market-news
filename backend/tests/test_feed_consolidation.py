"""Regressions found on the live week of 2026-09-21: duplicate cards and off-topic items."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.consolidate import consolidate_safe_duplicates
from app.core.deduplication import (
    coverage_of_same_named_release,
    titles_are_safe_lexical_match,
    titles_are_same_outlet_paraphrase,
    titles_are_same_release_wording,
    title_versioned_entities,
)
from app.core.feed import is_feed_in_scope
from app.core.parser import ArticleData
from app.core.pipeline import IntelligencePipeline
from app.models.event import Event, EventArticle
from app.models.source import Source
from app.models.article import Article


def test_specific_republished_headline_is_a_safe_lexical_match():
    title = "Investigation Reveals Failures of US Border Surveillance Technology"
    assert titles_are_safe_lexical_match(title, title)


def test_generic_identical_headline_is_still_not_a_lexical_match():
    assert not titles_are_safe_lexical_match(
        "OpenAI Announces Update",
        "OpenAI Announces Update",
    )


def test_same_outlet_border_paraphrases_match_and_distinct_posts_do_not():
    assert titles_are_same_outlet_paraphrase(
        "Investigation Reveals Failures of US Border Surveillance Technology",
        "Investigation Reveals Failures in US-Mexico Border Surveillance Technology",
    )
    assert not titles_are_same_outlet_paraphrase(
        "22 Nations Call for Global AI Oversight Body",
        "Anthropic and OpenAI make claims of breakthroughs amid scrutiny",
    )
    assert not titles_are_same_outlet_paraphrase(
        "Baseten Becomes Supported Inference Provider on Hugging Face Hub",
        "DeepInfra Becomes Supported Inference Provider on Hugging Face Hub",
    )


def test_release_wording_matches_named_model_not_availability_or_other_product():
    assert titles_are_same_release_wording(
        "Release of Claude Opus 5.5",
        "Introduction of Claude Opus 5.5 Model",
    )
    assert not titles_are_same_release_wording(
        "Introduction of GPT-6 Sol and Luna Models",
        "GPT-6 Sol and Luna Models Now Available on Amazon Bedrock",
    )
    assert not titles_are_same_release_wording(
        "Introduction of GPT-6 Astra by Parallel",
        "Higgsfield AI Launches GPT-6 Astra for Video Ad Creation",
    )
    assert title_versioned_entities("Release of Claude Opus 5.5") == ["Claude Opus 5.5"]


def test_generic_coverage_of_a_named_release_merges_and_availability_does_not():
    assert coverage_of_same_named_release(
        "Introduction of GPT-6 Sol and Luna Models",
        "https://openai.com/index/introducing-gpt-6-sol-and-luna",
        "OpenAI Launches Two New Models",
        "https://techcrunch.com/2026/09/22/openai-launches-gpt-6-sol-and-luna",
    )
    assert coverage_of_same_named_release(
        "Introduction of Claude Opus 5.5 Model",
        "https://www.anthropic.com/claude-opus-5-5",
        "Anthropic announces strongest-performing model",
        "https://techcrunch.com/2026/09/22/anthropic-releases-opus-5-5-with-lower-prices",
    )
    assert not coverage_of_same_named_release(
        "Introduction of GPT-6 Sol and Luna Models",
        "https://openai.com/index/introducing-gpt-6-sol-and-luna",
        "GPT-6 Sol and Luna Models Now Available on Amazon Bedrock",
        "https://aws.amazon.com/blogs/machine-learning/gpt-6-sol-and-luna-on-amazon-bedrock",
    )
    assert not coverage_of_same_named_release(
        "Introduction of Claude Opus 5.5 Model",
        "https://www.anthropic.com/claude-opus-5-5",
        "Acme implements Claude Opus 5.5 for support workflows",
        "https://example.com/acme-implements-claude-opus-5-5",
    )
    assert not coverage_of_same_named_release(
        "ChatGPT Launches GPT-5.6 Sol and Luna",
        "https://openai.com/index/gpt-5-6-sol",
        "OpenAI Launches Ultrafast API Service Tier for GPT-5.6 Sol",
        "https://openai.com/index/gpt-5-6-sol-ultrafast",
    )
    assert not coverage_of_same_named_release(
        "ChatGPT Launches GPT-5.6 Sol and Luna",
        "https://openai.com/index/gpt-5-6-sol",
        "MIT Researcher Utilizes GPT-5.6 Sol with Codex for Quantum Computing",
        "https://openai.com/index/mit-gpt-5-6-sol",
    )


def test_rebar_firmware_is_out_of_the_week_feed_and_inference_hardware_stays():
    assert not is_feed_in_scope(
        "Release of ReBarUEFI Driver for Resizable BAR Support",
        "The ReBarUEFI driver enables Resizable BAR on systems that do not officially support it, "
        "providing functionality for Intel Arc GPUs.",
        "community",
    )
    assert is_feed_in_scope(
        "NVIDIA ships a new inference GPU",
        "The chip is aimed at model inference clusters.",
        "secondary",
    )


def test_feed_scope_keeps_ai_and_curated_sources():
    assert is_feed_in_scope("OpenAI Academy Launches New Learning Paths", "Courses.", "primary")
    assert is_feed_in_scope(
        "Investigation Reveals Failures of US Border Surveillance Technology",
        "Towers missed people who passed through monitored areas.",
        "secondary",
    )
    assert is_feed_in_scope(
        "US Criticizes Australia's Proposed Algorithm Opt-Out Laws",
        "The statement concerns recommendation algorithms.",
        "community",
    )
    assert not is_feed_in_scope(
        "People Turn to Cigarettes to Quit Vaping",
        "A personal story about nicotine habits.",
        "community",
    )
    assert not is_feed_in_scope(
        "Discounts on TechCrunch Disrupt 2026 Passes Announced",
        "Conference pass prices were reduced.",
        "secondary",
    )


def test_same_outlet_paraphrase_merges_in_pipeline(db_session):
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    source = db_session.query(Source).first()
    first = pipeline.process_article(
        ArticleData(
            title="Investigation Reveals Failures of US Border Surveillance Technology",
            url="https://www.technologyreview.com/2026/09/21/border-a",
            content="An investigation documented failures of border surveillance towers over a thousand cases.",
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    second = pipeline.process_article(
        ArticleData(
            title="Investigation Reveals Failures in US-Mexico Border Surveillance Technology",
            url="https://www.technologyreview.com/2026/09/21/border-b",
            content="The same investigation described failures in US-Mexico border surveillance technology.",
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    assert first is not None and second is not None
    assert first.id == second.id
    links = db_session.query(EventArticle).filter(EventArticle.event_id == first.id).all()
    assert len(links) == 2


def test_consolidate_merges_release_wording_and_keeps_higher_importance(db_session):
    source = db_session.query(Source).first()
    source.tier = "community"
    now = datetime.now(timezone.utc)
    intro = Event(
        id=uuid.uuid4(),
        headline="Introduction of Claude Opus 5.5 Model",
        short_summary="Anthropic introduced Claude Opus 5.5.",
        importance_score=85,
        primary_source_id=source.id,
        article_url="https://www.anthropic.com/claude-opus-5-5",
        event_time=now,
        entities=["Claude Opus 5.5"],
    )
    release = Event(
        id=uuid.uuid4(),
        headline="Release of Claude Opus 5.5",
        short_summary="A catalog page noted the Claude Opus 5.5 release.",
        importance_score=50,
        primary_source_id=source.id,
        article_url="https://artificialanalysis.ai/models/claude-opus-5-5",
        event_time=now + timedelta(minutes=20),
        entities=[],
    )
    db_session.add_all([intro, release])
    db_session.flush()
    article = Article(
        id=uuid.uuid4(),
        source_id=source.id,
        url="https://artificialanalysis.ai/models/claude-opus-5-5",
        title=release.headline,
        raw_content="Claude Opus 5.5 release notes.",
        hash="abc123",
        published_at=now,
    )
    db_session.add(article)
    db_session.flush()
    db_session.add(EventArticle(event_id=release.id, article_id=article.id, link_type="primary"))
    db_session.commit()

    merged = consolidate_safe_duplicates(db_session)
    db_session.expire_all()
    assert merged == 1
    live = db_session.query(Event).filter(Event.superseded_by_id.is_(None)).one()
    assert live.headline == "Introduction of Claude Opus 5.5 Model"
    links = db_session.query(EventArticle).filter(EventArticle.event_id == live.id).all()
    assert len(links) == 1
    assert links[0].link_type == "supporting"
