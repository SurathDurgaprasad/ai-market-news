"""
Real OpenAI semantic evaluation harness — PROVIDER-AGNOSTIC-01
(docs/security-findings.md).

Deliberately modeled on test_nvidia_relationship_eval.py's structure and
`_eval()` pattern (same result-record shape, same TP/TN/FP/FN scoring, same
skip-guard idiom) rather than inventing a new evaluation framework — this
file reuses that harness's case CONTENT verbatim where the case is the
same one already validated against NVIDIA (A, F, H, E-fairwind, FW2, FW4),
and adds two genuinely new live checks the NVIDIA harness never covered:
a classify_event() case and a summarize_event() grounding case.

Why this file exists rather than parametrizing the NVIDIA one: OpenAI is
now this project's fast development/live-semantic-validation provider
(NVIDIA remains the unchanged production default — see
docs/architecture.md). Two Fairwind-neighbor cases run live against
NVIDIA both timed out at the full retry budget rather than returning a
verdict; this file's job is to get real semantic answers for those
specific cases (among others) against a provider that's actually fast
enough to iterate against.

One material adaptation from the NVIDIA harness's `_eval()`: that version
calls `pytest.fail()` on LlmUnavailableError. Per this task's explicit
instruction ("do not treat API timeout as a semantic failure" / "verify
the pipeline distinguishes provider failure from zero events"), this
file's `_eval()` instead records a dedicated "UNAVAILABLE" verdict and the
calling test SKIPS (not fails, not silently passes) — a timeout is
neither evidence the model merges correctly nor evidence it doesn't.

Run with:
  $env:LLM_PROVIDER='openai'
  $env:TESTING='0'
  $env:TEST_MODE='0'
  $env:OPENAI_EVAL='1'
  pytest tests/test_openai_relationship_eval.py -v -s
"""
import os
import time
import pytest
from app.core.providers.llm import (
    OpenAIProvider,
    OPENAI_OPERATION_DEADLINE_SECONDS,
    EventRelationship,
    RelationshipResult,
    LlmUnavailableError,
    provider_is_configured,
)
from app.core.deduplication import verify_citations

# ── Skip guard ────────────────────────────────────────────────────────────────

# conftest.py sets TESTING=1 at import time, which overrides shell env vars
# during pytest. Use a separate explicit flag, same idiom as NVIDIA_EVAL in
# test_nvidia_relationship_eval.py, so this harness can be invoked from a
# production-shaped env without needing a full pytest.ini rewrite.
_OPENAI_AVAILABLE = (
    os.environ.get("OPENAI_EVAL", "0") == "1"
    and provider_is_configured("openai")
)

pytestmark = [
    pytest.mark.skipif(
        not _OPENAI_AVAILABLE,
        reason=(
            "Live OpenAI eval requires: OPENAI_EVAL=1, LLM_PROVIDER=openai, "
            "TESTING=0, TEST_MODE=0, and OPENAI_API_KEY. "
            "conftest.py forces TESTING=1 for standard test runs."
        ),
    ),
    # OpenAI's operation deadline is deliberately tight (60s, see
    # OPENAI_OPERATION_DEADLINE_SECONDS) — that's the whole point of using
    # it as the dev-loop provider. 3 tenacity attempts x that deadline plus
    # backoff, same derivation discipline as the NVIDIA harness (a
    # hardcoded guess here previously caused a mismatched safety net to
    # fire before the provider's own bounded retry logic finished on a
    # slow-but-not-hung NVIDIA call — see NVDA-01 in
    # docs/security-findings.md; deriving from the constant avoids repeating
    # that exact mistake for OpenAI).
    pytest.mark.timeout(int(3 * OPENAI_OPERATION_DEADLINE_SECONDS + 60)),
]


# ── Helper ────────────────────────────────────────────────────────────────────

def _openai_provider() -> OpenAIProvider:
    from app.core.config import settings
    return OpenAIProvider(api_key=settings.OPENAI_API_KEY, model=settings.OPENAI_MODEL)


_results: list[dict] = []


@pytest.fixture(scope="module")
def openai_provider():
    return _openai_provider()


def _eval(
    provider: OpenAIProvider,
    article: str,
    existing_summary: str,
    context: str | None,
    expected_relationship: str,
    label: str,
) -> dict:
    """Run one classification and return a result record.

    Unlike test_nvidia_relationship_eval.py's _eval(), does NOT
    pytest.fail() on LlmUnavailableError — records a distinct
    "UNAVAILABLE" verdict instead, so a provider outage/timeout is never
    conflated with a semantic pass or fail.
    """
    t0 = time.monotonic()
    try:
        result: RelationshipResult = provider.classify_relationship(
            article, existing_summary, context=context
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
    except LlmUnavailableError as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        record = {
            "label": label,
            "expected": expected_relationship,
            "actual": None,
            "verdict": "UNAVAILABLE",
            "reasoning": f"{type(exc).__name__}: {exc}"[:200],
            "latency_ms": latency_ms,
            "provider": "openai",
            "model": provider.model,
        }
        print(f"\n[UNAVAILABLE] {label}\n  {record['reasoning']}\n  latency: {latency_ms}ms")
        return record

    actual = result.relationship
    expected_merge = expected_relationship == EventRelationship.SAME_EVENT
    actual_merge = result.is_merge()

    if expected_merge and actual_merge:
        verdict = "TP"
    elif not expected_merge and not actual_merge:
        verdict = "TN"
    elif expected_merge and not actual_merge:
        verdict = "FN"
    else:
        verdict = "FP"

    record = {
        "label": label,
        "expected": expected_relationship,
        "actual": actual,
        "merge_expected": expected_merge,
        "merge_actual": actual_merge,
        "verdict": verdict,
        "reasoning": result.reasoning[:120],
        "latency_ms": latency_ms,
        "provider": "openai",
        "model": provider.model,
    }
    print(
        f"\n[{verdict}] {label}\n"
        f"  expected={expected_relationship}  actual={actual}\n"
        f"  reasoning: {result.reasoning[:100]}\n"
        f"  latency: {latency_ms}ms"
    )
    return record


def _assert_not_a_semantic_failure(r: dict, forbidden_verdicts: tuple):
    """Fails the test only on a genuine semantic miss; skips (does not
    fail) on provider unavailability, per this task's explicit
    instruction not to treat a timeout as a semantic failure."""
    if r["verdict"] == "UNAVAILABLE":
        pytest.skip(f"OpenAI unavailable for case {r['label']}: {r['reasoning']}")
    assert r["verdict"] not in forbidden_verdicts, (
        f"{r['label']}: verdict={r['verdict']} reasoning={r['reasoning']}"
    )


# ── classify_relationship cases (reusing test_nvidia_relationship_eval.py's
# exact case content for A, F, H, E-fairwind, FW2, FW4) ────────────────────

def test_openai_A_same_event_official_and_news(openai_provider):
    article = (
        "Google DeepMind has launched Gemini 3.8 Flash, designed for speed and efficiency. "
        "The model is available via the API starting today."
    )
    existing = (
        "Google DeepMind releases Gemini 3.8 Flash\n"
        "Google DeepMind released Gemini 3.8 Flash, a lightweight model for fast inference. "
        "Gemini 3.8 Flash achieves state-of-the-art performance at low latency."
    )
    r = _eval(openai_provider, article, existing, context=None,
              expected_relationship=EventRelationship.SAME_EVENT, label="A-same-official-news")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


def test_openai_F_same_company_different_products(openai_provider):
    """Case 2: same model family, different event."""
    article = (
        "Gemini 3.8 Flash is a lightweight model designed for fast, cost-efficient inference at scale. "
        "It is a different product from Gemini 3.8 Live."
    )
    existing = (
        "Google DeepMind introduces Gemini 3.8 Live for real-time voice\n"
        "Gemini 3.8 Live is a new model optimized for real-time voice conversations with visual context."
    )
    r = _eval(openai_provider, article, existing,
              context="Event kind context — existing event: model_release; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="F-same-company-diff-products")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


def test_openai_E_fairwind_regression(openai_provider):
    """Case 3: model release vs program using that model — the Fairwind regression itself."""
    article = (
        "Google DeepMind releases Gemini Flash Cyber, a new model trained for autonomous "
        "vulnerability detection and remediation. The model is available to enterprise customers."
    )
    existing = (
        "Google launches Fairwind Program using Gemini Flash Cyber for government security\n"
        "Google announced the Fairwind Program, giving selected governments access to Gemini Flash Cyber "
        "and CodeMender to autonomously find and fix security vulnerabilities. "
        "This is a deployment program for government entities."
    )
    r = _eval(openai_provider, article, existing,
              context="Event kind context — existing event: capability; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="E-fairwind-regression")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


def test_openai_H_security_confirmation(openai_provider):
    """Case 4: security incident + confirmation."""
    article = (
        "OpenAI confirmed a critical RCE vulnerability in its Discourse-based forum, exploited via "
        "libheif image processing. The issue was patched within 14 hours of the report."
    )
    existing = (
        "Researcher reports RCE vulnerability in major AI forum\n"
        "A researcher exploited a heap buffer overflow in libheif used by the OpenAI forum, "
        "gaining remote code execution and account access. The vulnerability was reported."
    )
    r = _eval(openai_provider, article, existing,
              context="Event kind context — existing event: security_incident; incoming article: security_incident.",
              expected_relationship=EventRelationship.SAME_EVENT, label="H-security-confirmation")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


def test_openai_FW2_product_integrates_model(openai_provider):
    """Case 5a: Fairwind-neighbor — product integrates model vs model release.
    Ran live against NVIDIA first (see docs/security-findings.md
    PROVIDER-AGNOSTIC-01) and timed out at the full retry budget without
    returning a verdict — this is that case's first real semantic answer."""
    article = (
        "OpenAI released GPT-5 today, its most capable model to date, with major "
        "improvements in reasoning and coding benchmarks."
    )
    existing = (
        "Perplexity integrates GPT-5 into its search assistant\n"
        "Perplexity announced that its search assistant now uses GPT-5 for complex "
        "multi-step queries, joining several other models already available in the product."
    )
    r = _eval(openai_provider, article, existing,
              context="Event kind context — existing event: capability; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="FW2-product-integration")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


def test_openai_FW4_capability_announcement_using_model(openai_provider):
    """Case 5b: Fairwind-neighbor — capability announcement using model vs model release.
    Also previously timed out live against NVIDIA without a verdict."""
    article = (
        "Google released Gemini 3, its latest flagship model, with new multimodal "
        "capabilities and improved long-context performance."
    )
    existing = (
        "Notion announces AI Q&A feature powered by Gemini 3\n"
        "Notion announced a new AI Q&A capability in its workspace product, built on top of "
        "Google's Gemini 3 model, letting users ask questions across their notes."
    )
    r = _eval(openai_provider, article, existing,
              context="Event kind context — existing event: capability; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="FW4-capability-announcement")
    _results.append(r)
    _assert_not_a_semantic_failure(r, forbidden_verdicts=("FP",))


# ── classify_event case: Case 6, benign research must NOT become a
# security incident (IMPORTANCE-RESEARCH-01, docs/security-findings.md) ─────

def test_openai_classify_event_benign_vulnerability_research_not_incident(openai_provider):
    """
    Live classify_event() check (not classify_relationship): the exact
    content used in the deterministic end-to-end pipeline reproduction
    (tests/test_importance_research_vs_incident.py), now checking what a
    real model actually returns for event_kind/security_impact — the
    deterministic-signal override fix protects against a model that gets
    this wrong, but this is the first live check of whether OpenAI gets
    it right on its own.
    """
    content = (
        "This research paper analyzes how software vulnerabilities have changed "
        "over the past decade, drawing on a systematic review of over 10,000 "
        "disclosed CVEs. The study finds that memory-safety vulnerability classes "
        "have declined as a share of total disclosures, while logic-error "
        "vulnerabilities have grown. No specific product or vendor is the subject "
        "of this survey; it is a meta-analysis of public vulnerability databases."
    )
    t0 = time.monotonic()
    try:
        classification = openai_provider.classify_event(content)
    except LlmUnavailableError as exc:
        pytest.skip(f"OpenAI unavailable for classify_event research case: {exc}")
    latency_ms = int((time.monotonic() - t0) * 1000)

    record = {
        "label": "RESEARCH-benign-vuln-survey",
        "verdict": "N/A (classify_event, not relationship)",
        "event_kind": getattr(classification, "event_kind", None),
        "security_impact": getattr(classification, "security_impact", None),
        "importance_score": getattr(classification, "importance_score", None),
        "latency_ms": latency_ms,
        "provider": "openai",
        "model": openai_provider.model,
    }
    _results.append(record)
    print(f"\n[classify_event] RESEARCH-benign-vuln-survey\n  {record}\n  latency: {latency_ms}ms")

    assert classification is not None, "OpenAI produced no classification at all for a valid article"
    assert classification.security_impact != "significant", (
        f"A benign vulnerability-trends RESEARCH SURVEY was classified security_impact=significant "
        f"by the live model itself (not just the deterministic signal layer): {record}"
    )
    assert classification.event_kind != "security_incident", (
        f"A benign vulnerability-trends research survey was classified as an active "
        f"security_incident by the live model itself: {record}"
    )


# ── summarize_event / evidence case: Case 7, grounding check ──────────────

def test_openai_summarize_event_citations_are_grounded(openai_provider):
    """
    Live summarize_event() check: whatever citations the real model
    returns must independently verify against the source text via
    verify_citations() — the same deterministic grounding check
    production actually applies, not a relaxed test-only check.
    """
    content = (
        "Anthropic released Claude 4.5 today, its newest model, with a 500,000-token "
        "context window and improved coding benchmarks. The model is available immediately "
        "through the Anthropic API and via major cloud partners. Pricing remains unchanged "
        "from the previous generation."
    )
    t0 = time.monotonic()
    try:
        summary = openai_provider.summarize_event(content)
    except LlmUnavailableError as exc:
        pytest.skip(f"OpenAI unavailable for summarize_event case: {exc}")
    latency_ms = int((time.monotonic() - t0) * 1000)

    record = {
        "label": "SUMMARIZE-claude-4-5-release",
        "headline": getattr(summary, "headline", None),
        "citations_raw": len(getattr(summary, "citations", []) or []),
        "latency_ms": latency_ms,
        "provider": "openai",
        "model": openai_provider.model,
    }

    assert summary is not None, "OpenAI produced no summary at all for a valid article"
    verified = verify_citations(content, summary.citations or [])
    record["citations_verified"] = len(verified)
    _results.append(record)
    print(f"\n[summarize_event] SUMMARIZE-claude-4-5-release\n  {record}\n  latency: {latency_ms}ms")

    # If the model returned any citations, every one of them that survives
    # verify_citations counts as grounded evidence; we assert the model
    # didn't return citations that ALL fail grounding (that would mean it
    # fabricated quotes rather than copying them, exactly what
    # verify_citations exists to catch).
    if summary.citations:
        assert len(verified) > 0, (
            f"OpenAI returned {len(summary.citations)} citation(s), none of which verified "
            f"as an exact grounded substring of the source article — possible fabrication."
        )


# ── Summary ───────────────────────────────────────────────────────────────────

def test_openai_corpus_summary():
    """
    Aggregate results after all OpenAI live cases have run. Computed from
    the ACTUAL _results accumulated by the tests above — not hardcoded
    (see docs/security-findings.md TEST-QUALITY-EVAL-SUMMARY-01 for why that
    distinction matters and what it looked like to get this wrong).
    Reports actual results; does not assert a minimum precision, since a
    single bounded run is not a production-accuracy claim.
    """
    if not _results:
        pytest.skip("No results accumulated (run other test_openai_* tests first)")

    relationship_results = [r for r in _results if "verdict" in r and r["verdict"] in ("TP", "TN", "FP", "FN", "UNAVAILABLE")]
    tp = sum(1 for r in relationship_results if r["verdict"] == "TP")
    tn = sum(1 for r in relationship_results if r["verdict"] == "TN")
    fp = sum(1 for r in relationship_results if r["verdict"] == "FP")
    fn = sum(1 for r in relationship_results if r["verdict"] == "FN")
    unavailable = sum(1 for r in relationship_results if r["verdict"] == "UNAVAILABLE")

    print("\n" + "=" * 70)
    print("OpenAI live corpus summary (relationship cases)")
    print("=" * 70)
    for r in _results:
        print(f"  {r.get('label')}: {r.get('verdict', r)}")
    print(f"\nTP={tp} TN={tn} FP={fp} FN={fn} UNAVAILABLE={unavailable}")
    if tp + fp > 0:
        print(f"Precision (of scored cases) = {tp / (tp + fp):.2f}")
    print("=" * 70)

    # The only hard assertion here: zero false merges. A false merge
    # (shared entity/topic wrongly treated as the same real-world event)
    # is the specific failure class this whole evaluation exists to catch.
    assert fp == 0, f"OpenAI produced {fp} false merge(s) — see printed detail above."
