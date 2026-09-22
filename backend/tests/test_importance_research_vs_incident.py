"""
Phase 1H: hard case explicitly named in the operating brief — "security
keyword + harmless research". test_importance_adversarial.py already
documented this as a KNOWN LIMITATION at the infer_event_signals() level
but never verified whether it's actually exploitable end-to-end through
the real pipeline. It is.

Root cause: infer_event_signals() checks its security regex FIRST and
returns immediately on a match — "vulnerabilit\\w+" anywhere in the
title/summary/first-3000-chars matches "a survey of vulnerability
trends" exactly the same as it matches an active incident report, before
the function's own research-paper detection further down ever runs.

This alone would just be an inaccurate standalone function. It becomes a
real pipeline defect via pipeline.py's calibration override:

    if security == "none" and inf_sec != "none":
        security = inf_sec

If the LLM correctly classifies a benign research article as
security_impact="none" (or simply defaults to "none", which
EventClassification's Pydantic default already is), the deterministic
signal's false positive OVERRIDES that correct judgment — inflating a
benign research survey into a fabricated "security_incident" at
"significant" severity, contradicting the LLM's own correct assessment.
"""
from app.core.pipeline import IntelligencePipeline
from app.core.providers.source import TestSourceProvider
from app.models.source import Source
from app.core.parser import ArticleData


def test_vulnerability_research_survey_is_not_classified_as_security_incident(db_session):
    """
    End-to-end reproduction through the real pipeline (not just the
    standalone infer_event_signals()/calibrate_importance_score() unit
    tests in test_importance_adversarial.py) — TestLLMProvider's fixture
    defaults to event_kind="other" and security_impact="none" (both are
    EventClassification's own Pydantic defaults, standing in for "the LLM
    made no specific claim either way" — a realistic case, not a
    contrived one), so this exercises exactly the deterministic-override
    path pipeline.py actually runs in production.
    """
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    provider = TestSourceProvider()
    source = db_session.query(Source).first()

    article = ArticleData(
        title="A survey of vulnerability trends in 2024",
        url="https://arxiv.org/papers/vuln-survey-2024",
        content=(
            "This research paper analyzes how software vulnerabilities have changed "
            "over the past decade, drawing on a systematic review of over 10,000 "
            "disclosed CVEs. The study finds that memory-safety vulnerability classes "
            "have declined as a share of total disclosures, while logic-error "
            "vulnerabilities have grown. No specific product or vendor is the subject "
            "of this survey; it is a meta-analysis of public vulnerability databases."
        ),
        published_at=None,
    )

    event = pipeline.process_article(article, source.id)

    assert event is not None
    reasoning = event.importance_reasoning or {}
    actual_kind = reasoning.get("event_kind")
    actual_security = reasoning.get("security_impact")

    assert actual_kind != "security_incident", (
        f"A vulnerability-trends RESEARCH SURVEY was classified as an active "
        f"security_incident (importance_score={event.importance_score}). Deterministic "
        f"keyword matching on 'vulnerabilit' overrode the LLM's own classification."
    )
    assert actual_security != "significant", (
        f"A vulnerability-trends research survey was assigned security_impact=significant "
        f"(importance_score={event.importance_score}) — importance must depend on event "
        f"substance (an academic survey), not keyword presence alone."
    )
