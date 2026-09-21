"""
Adversarial clustering tests.

Each test corresponds to one of the 20 required adversarial scenarios from the PRD.
Tests use the TestLLMProvider which uses "duplicate_trigger" in content as a deterministic
signal for is_same_event=True, and its absence as is_same_event=False.

Covered scenarios:
  1. Same event / different headlines (adversarial_1_*)
  2. Same event / multiple sources (via test_adversarial_same_event_different_headlines)
  3. Same company / different events (adversarial_2)
  4. Same model family / different distinct events (adversarial_5_*)  [NEW]
  6. Announcement + technical documentation for the same event (adversarial_6_*)  [NEW]
  8. Rumor + official confirmation (adversarial_3_*)
  9. Correction (adversarial_4)
 11. Multi-hour/day reporting delay (adversarial_11_*)  [NEW]
 12. Multiple languages (adversarial_12_*)  [NEW]
 14. Community discovery + official confirmation (adversarial_14_*)  [NEW]
"""
import pytest
from app.core.pipeline import IntelligencePipeline
from app.core.providers.source import TestSourceProvider
from app.models.source import Source

def test_adversarial_same_event_different_headlines(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    r1 = provider.fetch("https://openai.com", "adversarial_1_official")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    
    r2 = provider.fetch("https://reuters.com", "adversarial_1_reuters")
    event2 = pipeline.process_article(r2["data"], source_id)
    
    # Even though titles differ entirely ("Introducing GPT-4o" vs "OpenAI unveils new AI model..."),
    # they describe the exact same event. Our LLM mock uses 'duplicate_trigger' to simulate a positive semantic match.
    assert event1 is not None
    assert event2 is not None
    assert event1.id == event2.id

def test_adversarial_same_company_unrelated_announcement(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    r1 = provider.fetch("https://openai.com", "adversarial_1_official")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    
    # Now they announce an office lease (shares OpenAI entity, but completely different event)
    # The mock will return False for is_same_event because 'duplicate_trigger' is not in the text
    r2 = provider.fetch("https://openai.com", "adversarial_2_unrelated_announcement")
    event2 = pipeline.process_article(r2["data"], source_id)
    
    assert event1 is not None
    assert event2 is not None
    assert event1.id != event2.id

def test_adversarial_rumor_followed_by_official(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    
    r1 = provider.fetch("https://techleaks.com", "adversarial_3_rumor")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)
    
    # Official announcement a week later. It IS the same real-world event (Claude 4 release).
    # Wait, the prompt states: "Treat new distinct events as different... but if it's the exact same event..."
    # The rumor and official announcement might be clustered if the LLM determines they describe the same core event.
    r2 = provider.fetch("https://anthropic.com", "adversarial_3_official")
    event2 = pipeline.process_article(r2["data"], source_id)
    
    assert event1 is not None
    assert event2 is not None
    assert event1.id == event2.id

def test_adversarial_correction(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()

    r1 = provider.fetch("https://news.com", "adversarial_4_correction")
    source_id = db_session.query(Source).first().id
    event1 = pipeline.process_article(r1["data"], source_id)

    # A correction is a separate event or an update. The DB logic should ingest it correctly.
    assert event1 is not None


# ── Test 4: Same model family / different distinct events ─────────────────────

def test_adversarial_same_model_family_different_events(db_session):
    """
    Test 4: Gemini 2.0 Ultra vs Gemini 2.0 Pro are DIFFERENT events even though
    they share the 'Gemini 2.0' model family. The LLM mock returns False (no
    duplicate_trigger in either fixture) so they should produce two events.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    r1 = provider.fetch("https://deepmind.google", "adversarial_5_gemini_ultra")
    event1 = pipeline.process_article(r1["data"], source_id)

    r2 = provider.fetch("https://deepmind.google", "adversarial_5_gemini_pro")
    event2 = pipeline.process_article(r2["data"], source_id)

    assert event1 is not None
    assert event2 is not None
    # Must produce two separate events — different products despite shared family name
    assert event1.id != event2.id


# ── Test 6: Announcement + technical documentation ───────────────────────────

def test_adversarial_announcement_then_technical_doc(db_session):
    """
    Test 6: The initial model announcement and the technical API documentation
    published hours later are about THE SAME real-world event (Claude 4 Sonnet release).
    Both fixtures contain 'duplicate_trigger' so the LLM mock returns True.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    r1 = provider.fetch("https://anthropic.com", "adversarial_6_announcement")
    event1 = pipeline.process_article(r1["data"], source_id)

    r2 = provider.fetch("https://docs.anthropic.com", "adversarial_6_technical_doc")
    event2 = pipeline.process_article(r2["data"], source_id)

    assert event1 is not None
    assert event2 is not None
    # Both should collapse to ONE canonical event
    assert event1.id == event2.id


# ── Test 11: Multi-hour / multi-day reporting delay ──────────────────────────

def test_adversarial_multi_day_reporting_delay(db_session):
    """
    Test 11: A secondary outlet reports the same event >24 hours later.
    Both contain 'duplicate_trigger' so they should cluster to ONE event.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    r1 = provider.fetch("https://x.ai", "adversarial_11_initial")
    event1 = pipeline.process_article(r1["data"], source_id)

    r2 = provider.fetch("https://arstechnica.com", "adversarial_11_delayed_report")
    event2 = pipeline.process_article(r2["data"], source_id)

    assert event1 is not None
    assert event2 is not None
    # Despite the day-gap in publication times, same real-world event → ONE card
    assert event1.id == event2.id


# ── Test 12: Multiple languages ───────────────────────────────────────────────

def test_adversarial_multilingual_same_event(db_session):
    """
    Test 12: English and German reports about the same Meta Llama 4 release.
    Both contain 'duplicate_trigger' so the LLM mock confirms same event.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    r1 = provider.fetch("https://ai.meta.com", "adversarial_12_english")
    event1 = pipeline.process_article(r1["data"], source_id)

    r2 = provider.fetch("https://heise.de", "adversarial_12_german")
    event2 = pipeline.process_article(r2["data"], source_id)

    assert event1 is not None
    assert event2 is not None
    # Cross-language reports of the same event → ONE canonical event
    assert event1.id == event2.id


# ── Test 14: Community discovery + official confirmation ──────────────────────

def test_adversarial_community_discovery_then_official_confirmation(db_session):
    """
    Test 14: Community discovers model weights on Hugging Face, then official
    announcement follows. Both contain 'duplicate_trigger' → should merge.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    r1 = provider.fetch("https://huggingface.co", "adversarial_14_community")
    event1 = pipeline.process_article(r1["data"], source_id)

    r2 = provider.fetch("https://deepseek.com", "adversarial_14_official")
    event2 = pipeline.process_article(r2["data"], source_id)

    assert event1 is not None
    assert event2 is not None
    # Community discovery + official announcement → ONE canonical event
    assert event1.id == event2.id


def test_adversarial_generic_identical_titles_are_not_merged(db_session):
    """
    Identical generic headlines with different facts must remain two events.
    Jaccard would otherwise false-merge "OpenAI Announces Update" with itself.
    """
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    e1 = pipeline.process_article(provider.fetch("u", "generic_title_board")["data"], source_id)
    e2 = pipeline.process_article(provider.fetch("u", "generic_title_office")["data"], source_id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


def test_adversarial_same_company_minutes_apart_different_products(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    e1 = pipeline.process_article(provider.fetch("u", "minutes_apart_model")["data"], source_id)
    e2 = pipeline.process_article(provider.fetch("u", "minutes_apart_other_gpu")["data"], source_id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


def test_adversarial_same_event_different_technical_terminology(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    e1 = pipeline.process_article(provider.fetch("u", "term_research")["data"], source_id)
    e2 = pipeline.process_article(provider.fetch("u", "term_journalism")["data"], source_id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id


def test_adversarial_research_preview_then_distinct_api_launch(db_session):
    """API availability after a research preview is a distinct event without duplicate_trigger."""
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id

    e1 = pipeline.process_article(provider.fetch("u", "mistral_large_research")["data"], source_id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_7_api_launch")["data"], source_id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


def test_clickbait_is_rejected_before_event_creation(db_session):
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id
    event = pipeline.process_article(provider.fetch("u", "clickbait_noise")["data"], source_id)
    assert event is None


def test_adversarial_similar_headline_conflicting_facts_are_not_merged(db_session):
    """Same company, similar GPT-5 headlines, opposite facts → two events."""
    pipeline = IntelligencePipeline(db_session)
    provider = TestSourceProvider()
    source_id = db_session.query(Source).first().id
    e1 = pipeline.process_article(provider.fetch("u", "conflicting_facts_available")["data"], source_id)
    e2 = pipeline.process_article(provider.fetch("u", "conflicting_facts_delayed")["data"], source_id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id
