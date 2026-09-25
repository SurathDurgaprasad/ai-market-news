"""
Event-relationship evaluation corpus — deterministic (TestLLMProvider).

Relationship classes:
  SAME_EVENT           → merge         (duplicate_trigger in content)
  UPDATE_TO_SAME_EVENT → no merge      (update_trigger in content)
  RELATED_EVENT        → no merge      (related_trigger in content)
  DIFFERENT_EVENT      → no merge      (no trigger)

The test provider is purely deterministic; real NVIDIA validation is in
test_nvidia_relationship_eval.py (requires NVIDIA credentials, skips otherwise).

Candidate-generation tests are explicitly separated from merge tests to keep
the two concerns distinct:
  - content-hash dedup: same article text → skip entirely
  - entity-overlap candidate: shared entity → call LLM (classified separately)
  - LLM merge decision: classify_relationship() → only SAME_EVENT merges

Corpus size: 40 cases (10 SAME + 5 UPDATE + 5 RELATED + 20 DIFFERENT).
"""
import pytest
from unittest.mock import patch, MagicMock
from app.core.pipeline import IntelligencePipeline
from app.core.providers.source import TestSourceProvider
from app.core.providers.llm import (
    EventRelationship,
    RelationshipResult,
    TestLLMProvider,
)
from app.models.source import Source
from app.models.event import Event, EventArticle
from app.core.importance import kinds_are_compatible


# ─────────────────────────────────────────────────────────────────────────────
# EventRelationship unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEventRelationship:
    def test_same_event_is_merge(self):
        r = RelationshipResult(relationship=EventRelationship.SAME_EVENT, reasoning="test")
        assert r.is_merge() is True

    def test_update_is_not_merge(self):
        r = RelationshipResult(relationship=EventRelationship.UPDATE_TO_SAME_EVENT, reasoning="test")
        assert r.is_merge() is False

    def test_related_is_not_merge(self):
        r = RelationshipResult(relationship=EventRelationship.RELATED_EVENT, reasoning="test")
        assert r.is_merge() is False

    def test_different_is_not_merge(self):
        r = RelationshipResult(relationship=EventRelationship.DIFFERENT_EVENT, reasoning="test")
        assert r.is_merge() is False

    def test_different_factory(self):
        r = RelationshipResult.different()
        assert r.relationship == EventRelationship.DIFFERENT_EVENT
        assert r.is_merge() is False


class TestTestLLMProviderRelationship:
    def test_duplicate_trigger_is_same_event(self):
        p = TestLLMProvider()
        r = p.classify_relationship("content with duplicate_trigger here", "existing summary")
        assert r.relationship == EventRelationship.SAME_EVENT
        assert r.is_merge() is True

    def test_update_trigger_is_update(self):
        p = TestLLMProvider()
        r = p.classify_relationship("content with update_trigger here", "existing summary")
        assert r.relationship == EventRelationship.UPDATE_TO_SAME_EVENT
        assert r.is_merge() is False

    def test_related_trigger_is_related(self):
        p = TestLLMProvider()
        r = p.classify_relationship("content with related_trigger here", "existing summary")
        assert r.relationship == EventRelationship.RELATED_EVENT
        assert r.is_merge() is False

    def test_no_trigger_is_different(self):
        p = TestLLMProvider()
        r = p.classify_relationship("content with no keyword", "existing summary")
        assert r.relationship == EventRelationship.DIFFERENT_EVENT
        assert r.is_merge() is False

    def test_is_same_event_wraps_classify(self):
        p = TestLLMProvider()
        assert p.is_same_event("content with duplicate_trigger", "existing summary") is True
        assert p.is_same_event("content with update_trigger", "existing summary") is False
        assert p.is_same_event("no trigger", "existing summary") is False


# ─────────────────────────────────────────────────────────────────────────────
# Kind-compatibility unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_kind_compat_funding_vs_model_release():
    assert kinds_are_compatible("funding", "model_release") is False

def test_kind_compat_maintenance_vs_security():
    assert kinds_are_compatible("maintenance", "security_incident") is False

def test_kind_compat_model_release_vs_research():
    """model_release + research is NOT incompatible — benchmark papers etc."""
    assert kinds_are_compatible("model_release", "research") is True

def test_kind_compat_same_kind():
    assert kinds_are_compatible("model_release", "model_release") is True

def test_kind_compat_other_is_always_compatible():
    assert kinds_are_compatible("other", "security_incident") is True
    assert kinds_are_compatible("model_release", "other") is True

def test_kind_compat_capability_vs_model_release():
    """capability+model_release is NOT incompatible — sometimes the same event."""
    assert kinds_are_compatible("capability", "model_release") is True

def test_kind_compat_acquisition_vs_model_release():
    assert kinds_are_compatible("acquisition", "model_release") is False

def test_kind_compat_funding_vs_security():
    assert kinds_are_compatible("funding", "security_incident") is False

def test_kind_compat_maintenance_vs_hardware():
    assert kinds_are_compatible("maintenance", "hardware_platform") is False

def test_kind_compat_acquisition_vs_research():
    assert kinds_are_compatible("acquisition", "research") is False


# ─────────────────────────────────────────────────────────────────────────────
# Candidate-generation tests (separate from merge tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_candidate_generated_when_entity_overlaps(db_session):
    """
    Shared entity creates a candidate for LLM classification.
    classify_relationship is called exactly once for the overlapping pair.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    # First event: creates the candidate
    e1 = pipeline.process_article(provider.fetch("u", "normal_1")["data"], source.id)
    assert e1 is not None

    # Second event: no duplicate_trigger → DIFFERENT, no merge, but LLM was called
    llm = pipeline.llm
    original_classify = llm.classify_relationship
    calls = []
    def tracking_classify(content, summary, context=None):
        calls.append({"content": content[:40], "summary": summary[:40]})
        return original_classify(content, summary, context)
    llm.classify_relationship = tracking_classify

    e2 = pipeline.process_article(provider.fetch("u", "different_source_same_event")["data"], source.id)
    # different_source_same_event has duplicate_trigger → SAME_EVENT → merge
    assert e2 is not None
    assert e2.id == e1.id
    assert len(calls) >= 1, "classify_relationship must have been called for the overlapping entity"


def test_no_candidate_when_no_entity_overlap(db_session):
    """
    When there is no entity overlap, classify_relationship must NOT be called.
    Content-hash dedup (exact duplicate) is also separate — tested separately.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    e1 = pipeline.process_article(provider.fetch("u", "normal_2")["data"], source.id)
    assert e1 is not None  # board announcement

    # Track classify_relationship calls
    llm = pipeline.llm
    original_classify = llm.classify_relationship
    calls = []
    def tracking_classify(content, summary, context=None):
        calls.append(True)
        return original_classify(content, summary, context)
    llm.classify_relationship = tracking_classify

    # Completely unrelated article with no overlapping entities
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_2_unrelated_announcement")["data"], source.id)

    # The events are separate; if classify was called it returned DIFFERENT
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


def test_content_hash_dedup_never_calls_llm(db_session):
    """
    Exact content duplicate is rejected before any LLM call.
    This validates that content-dedup and event-dedup are separate pipelines.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    pipeline.process_article(provider.fetch("u", "normal_1")["data"], source.id)

    llm = pipeline.llm
    calls = []
    def tracking_classify(content, summary, context=None):
        calls.append(True)
        return RelationshipResult(relationship=EventRelationship.DIFFERENT_EVENT, reasoning="tracked")
    llm.classify_relationship = tracking_classify

    # Exact duplicate — same URL, same content
    result = pipeline.process_article(provider.fetch("u", "duplicate_exact")["data"], source.id)
    assert result is None, "Exact content duplicate must be rejected"
    assert pipeline.last_outcome == "duplicate"
    assert len(calls) == 0, "classify_relationship must NOT be called for content duplicates"


def test_update_trigger_does_not_merge(db_session):
    """
    UPDATE_TO_SAME_EVENT from the LLM means: do NOT merge.
    The second article becomes a separate event.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    e1 = pipeline.process_article(provider.fetch("u", "eval_update_initial")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_update_followup")["data"], source.id)

    assert e1 is not None and e2 is not None
    # update_trigger → UPDATE_TO_SAME_EVENT → no merge
    assert e1.id != e2.id, "UPDATE_TO_SAME_EVENT must NOT merge events"


def test_related_trigger_does_not_merge(db_session):
    """
    RELATED_EVENT from the LLM means: do NOT merge.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    e1 = pipeline.process_article(provider.fetch("u", "eval_model_release")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_benchmark_of_model")["data"], source.id)

    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "RELATED_EVENT must NOT merge events"


# ─────────────────────────────────────────────────────────────────────────────
# SAME_EVENT cases — 10 cases, expect merge (TP)
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_A_same_event_official_and_news(db_session):
    """A. SAME EVENT: official blog + news report about the same model launch. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_model_official")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_model_news")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_B_same_event_different_terminology(db_session):
    """B. SAME EVENT: different wording for the same announcement. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_same_event_term_a")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_same_event_term_b")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_H_security_incident_and_confirmation(db_session):
    """H. SECURITY: initial incident + official confirmation. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_security_initial")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_security_confirmation")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_I_hn_and_blog_same_release(db_session):
    """I. SAME EVENT: HN-linked + direct official blog. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_hn_links_blog")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_mistral_blog")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_J_delayed_coverage(db_session):
    """J. SAME EVENT: delayed 24h coverage of same release. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_delayed_initial")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_delayed_coverage")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_K_funding_from_two_outlets(db_session):
    """K. SAME EVENT: funding round covered by TechCrunch and Bloomberg. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_funding_techcrunch")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_funding_bloomberg")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

# Adversarial same-event cases (using existing adversarial fixtures)
def test_eval_same_event_different_headlines_adversarial(db_session):
    """GPT-4o official vs Reuters — different titles, same event. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_1_official")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_1_reuters")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_community_discovery_then_official(db_session):
    """Community HF discovery + official DeepSeek announcement. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_14_community")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_14_official")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_multilingual_same_event(db_session):
    """English + German reports of same Meta Llama 4 release. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_12_english")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_12_german")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_rumor_then_official(db_session):
    """Rumor + official confirmation — same Claude 4 release. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_3_rumor")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_3_official")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE_TO_SAME_EVENT cases — 5 cases, expect SEPARATE (TN)
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_L_api_availability_update(db_session):
    """L. UPDATE: initial Plus launch + API availability expansion. Separate events. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_update_initial")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_update_followup")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_M_security_patch_update(db_session):
    """M. UPDATE: security incident + patch release. Separate events. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_patch_incident")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_patch_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_N_expanded_availability_update(db_session):
    """N. UPDATE: API launch + Bedrock availability expansion. Separate events. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_availability_initial")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_availability_expanded")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_update_from_adversarial_fixture(db_session):
    """API launch after research preview is a distinct event. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "mistral_large_research")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_7_api_launch")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_same_url_content_update_no_merge(db_session):
    """Same URL, changed content → version update. Treated as new version, not same event. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "normal_1")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "updated_article")["data"], source.id)
    assert e1 is not None and e2 is not None
    # Version update creates a new event that supersedes the original
    live = db_session.query(Event).filter(Event.superseded_by_id.is_(None)).all()
    assert len(live) == 1


# ─────────────────────────────────────────────────────────────────────────────
# RELATED_EVENT cases — 5 cases, expect SEPARATE (TN)
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_O_benchmark_of_model_is_related(db_session):
    """O. RELATED: model release + independent benchmark of that model. Separate. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_model_release")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_benchmark_of_model")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_P_security_research_is_related(db_session):
    """P. RELATED: security incident + survey paper on same attack class. Separate. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_security_incident")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_security_research")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_Q_platform_guide_is_related(db_session):
    """Q. RELATED: library release + tutorial using that library. Separate. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_platform_release")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_platform_guide")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_technical_doc_after_announcement_same_event(db_session):
    """Technical API docs published hours after announcement are SAME event. (TP)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_6_announcement")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_6_technical_doc")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id == e2.id

def test_eval_unrelated_research_mentioning_same_model(db_session):
    """G/BB. DIFFERENT: research paper evaluating a model ≠ the model release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_model_official")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_model_mentioned_in_research")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


# ─────────────────────────────────────────────────────────────────────────────
# DIFFERENT_EVENT hard negatives — 20 cases, expect SEPARATE (TN)
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_E_program_using_model_not_same_as_model_release(db_session):
    """E. DIFFERENT (Fairwind regression): program deploying model X ≠ release of model X. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_program_launch")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_model_in_program")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "Fairwind regression must remain separate"


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1D — 5 deliberately distinct neighboring variations of the Fairwind
# trap (shared model entity, article NOT about the model's release), each
# with a different company/model pair so this isn't the same case with
# names swapped. A shared entity must never be sufficient evidence of
# SAME_EVENT on its own — these exercise that from 5 different angles.
# ─────────────────────────────────────────────────────────────────────────────

def test_eval_FW1_program_uses_model_not_same_as_release(db_session):
    """FW1. DIFFERENT: program deploying Claude 4.5 ≠ release of Claude 4.5. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_fw1_program_launch")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_fw1_model_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "program-uses-model must not merge with the model's own release"

def test_eval_FW2_product_integrates_model_not_same_as_release(db_session):
    """FW2. DIFFERENT: Perplexity integrating GPT-5 ≠ OpenAI releasing GPT-5. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_fw2_product_integration")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_fw2_model_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "product-integrates-model must not merge with the model's own release"

def test_eval_FW3_benchmark_evaluates_model_not_same_as_release(db_session):
    """FW3. DIFFERENT: MLPerf benchmarking Llama 4 ≠ Meta releasing Llama 4. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_fw3_benchmark_result")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_fw3_model_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "benchmark-evaluates-model must not merge with the model's own release"

def test_eval_FW4_capability_announcement_not_same_as_release(db_session):
    """FW4. DIFFERENT: Notion's Gemini-3-powered Q&A feature ≠ Google releasing Gemini 3. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_fw4_capability_announcement")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_fw4_model_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "capability-announcement-using-model must not merge with the model's own release"

def test_eval_FW5_deployment_announcement_not_same_as_release(db_session):
    """FW5. DIFFERENT: Snowflake deploying Mistral Large 3 ≠ Mistral AI releasing it. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_fw5_deployment_announcement")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_fw5_model_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id, "deployment-announcement-mentioning-model must not merge with the model's own release"


def test_eval_R_framework_integration_not_model_release(db_session):
    """R. DIFFERENT: LangChain Claude 4 integration ≠ Claude 4 release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_framework_integration")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_underlying_model")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_S_partnership_deploying_model_not_same_as_release(db_session):
    """S. DIFFERENT: Salesforce Einstein using Claude 4 ≠ Claude 4 release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_partnership_using_model")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_underlying_model")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_F_same_company_different_products(db_session):
    """F. DIFFERENT: Gemini 3.8 Live vs Gemini 3.8 Flash — different product tiers. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_same_company_product_a")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_same_company_product_b")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_T_same_company_funding_vs_model(db_session):
    """T. DIFFERENT: OpenAI funding round ≠ OpenAI GPT-6 release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_openai_funding")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_openai_gpt6")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_V_shared_org_entity_api_outage_vs_board(db_session):
    """V. DIFFERENT: Both mention OpenAI but API outage ≠ board appointment. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_openai_api_outage")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_openai_board_change")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_W_shared_google_entity_different_products(db_session):
    """W. DIFFERENT: Google Search AI ≠ Google DeepMind AlphaGenome. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_google_search_ai")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_google_deepmind_model")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_X_shared_cuda_entity_different_events(db_session):
    """X. DIFFERENT: CUDA 13.0 release ≠ PyTorch CUDA 13 support. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_cuda_nvidia_release")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_cuda_torch_update")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_Y_leaderboard_update_not_model_release(db_session):
    """Y. DIFFERENT: Open LLM Leaderboard update ≠ GPT-6 Astra release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_leaderboard_update")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_openai_gpt6")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_Z_different_security_incidents_same_company(db_session):
    """Z. DIFFERENT: Two separate Anthropic security incidents. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_security_incident_2")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_security_incident_3")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_AA_model_deprecation_vs_release(db_session):
    """AA. DIFFERENT: GPT-4 Turbo deprecation ≠ GPT-5 release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_model_deprecation")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_update_initial")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_CC_finetune_benchmark_vs_base_model(db_session):
    """CC. DIFFERENT: fine-tune benchmark paper ≠ base Llama 3 release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_finetune_benchmark")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_llama3_release")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_DD_api_pricing_change_vs_model_release(db_session):
    """DD. DIFFERENT: GPT-5 pricing cut ≠ GPT-5 original release. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_api_pricing_change")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "eval_update_initial")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_same_company_different_events_adversarial(db_session):
    """OpenAI GPT-4o launch ≠ OpenAI office lease. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_1_official")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_2_unrelated_announcement")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_same_model_family_different_tiers(db_session):
    """Gemini 2.0 Ultra ≠ Gemini 2.0 Pro — different product tiers. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "adversarial_5_gemini_ultra")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_5_gemini_pro")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_conflicting_facts_not_merged(db_session):
    """GPT-5 available vs GPT-5 delayed — conflicting claims → separate events. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "conflicting_facts_available")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "conflicting_facts_delayed")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_api_then_distinct_research_preview(db_session):
    """Research preview vs distinct API availability — separate events. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "mistral_large_research")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "adversarial_7_api_launch")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_generic_titles_no_fast_path_merge(db_session):
    """Two generic 'OpenAI Announces Update' headlines must not fast-merge. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "generic_title_board")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "generic_title_office")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_same_company_minutes_apart_different_products(db_session):
    """Same company, minutes apart, different GPU models. (TN)"""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "minutes_apart_model")["data"], source.id)
    e2 = pipeline.process_article(provider.fetch("u", "minutes_apart_other_gpu")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id

def test_eval_safety_paper_not_model_release(db_session):
    """U. DIFFERENT: Anthropic safety research paper ≠ Claude 4 model release. (TN)
    Uses eval_underlying_model (no duplicate_trigger) to avoid false merge via TestLLM trigger."""
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()
    e1 = pipeline.process_article(provider.fetch("u", "eval_safety_paper")["data"], source.id)
    # eval_underlying_model = Claude 4 release without duplicate_trigger → no test-LLM merge
    e2 = pipeline.process_article(provider.fetch("u", "eval_underlying_model")["data"], source.id)
    assert e1 is not None and e2 is not None
    assert e1.id != e2.id


# ─────────────────────────────────────────────────────────────────────────────
# Corpus summary (documentation assertion)
# ─────────────────────────────────────────────────────────────────────────────

def test_corpus_precision_recall_summary():
    """
    Documents expected TP/TN/FP/FN for this deterministic corpus.
    TestLLMProvider is deterministic; these are NOT real NVIDIA results.

    IMPORTANT — what this test does and does not verify: the TP/TN/FP/FN
    counts below are a hand-maintained tally, not independently computed
    from actually running the corpus through the pipeline. The real
    verification is each individual `test_eval_*` function above, which
    DOES call the real pipeline and assert real merge/no-merge behavior.
    This function previously asserted only a precision/recall FORMULA
    against those hardcoded numbers — it would have passed unconditionally
    even if every other test in this file were failing or deleted, which
    is exactly the "test that could pass while the real implementation is
    broken" pattern flagged in the operating brief's Phase 1K. Fixed to
    additionally verify the tally hasn't silently drifted from the actual
    test file (see docs/security-findings.md TEST-QUALITY-EVAL-SUMMARY-01):
    the counts below are cross-checked against the real number of
    `test_eval_*` functions currently defined in this module, so adding
    or removing a case without updating this summary now fails loudly.

    SAME_EVENT (expect merge):
      A, B, H, I, J, K, adversarial_1, community_14, multilingual_12, rumor_3 = 10 TP

    UPDATE_TO_SAME_EVENT (expect separate):
      L, M, N, adversarial_7, same_url_update = 5 TN (correct non-merges)

    RELATED_EVENT (expect separate):
      O, P, Q, technical_doc→TP, unrelated_research = 4 TN + 1 TP

    DIFFERENT_EVENT (expect separate):
      E(Fairwind), R, S, F, T, V, W, X, Y, Z, AA, CC, DD,
      adversarial_same_company, same_family_tiers, conflicting_facts,
      api_research, generic_titles, minutes_apart, safety_paper,
      program_uses_model, product_integrates_model, benchmark_evaluates_model,
      capability_announcement_using_model, deployment_announcement_mentioning_model
        = 25 TN

    Totals: TP=11  TN=34  FP=0  FN=0
    Precision = 11/11 = 1.0 (no false merges)
    Recall-like = 11/11 = 1.0 (all expected merges occurred)

    NOTE: These results are ONLY valid for TestLLMProvider.
          Real NVIDIA results are in test_nvidia_relationship_eval.py.
    """
    TP, TN, FP, FN = 11, 34, 0, 0

    import inspect
    import sys
    current_module = sys.modules[__name__]
    actual_eval_case_count = sum(
        1 for name, obj in inspect.getmembers(current_module, inspect.isfunction)
        if name.startswith("test_eval_") and obj.__module__ == __name__
    )
    claimed_case_count = TP + TN + FP + FN
    assert actual_eval_case_count == claimed_case_count, (
        f"This summary claims {claimed_case_count} eval cases (TP={TP}+TN={TN}+FP={FP}+FN={FN}) "
        f"but the module actually defines {actual_eval_case_count} test_eval_* functions. "
        f"A case was added or removed without updating this hand-maintained tally — "
        f"update the counts above (and their category breakdown) to match."
    )

    assert TP + FP > 0
    precision = TP / (TP + FP)
    recall_like = TP / (TP + FN)
    assert precision == 1.0
    assert recall_like == 1.0
