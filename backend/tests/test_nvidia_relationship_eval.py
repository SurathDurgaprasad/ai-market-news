"""
Real NVIDIA semantic relationship evaluation harness.

Runs the 8 canonical corpus cases (A–H) through the live NVIDIA provider
(openai/gpt-oss-20b) and records:
  - expected relationship
  - model-returned relationship
  - reasoning
  - latency (ms)
  - provider / model name
  - TP / FP / TN / FN

Tests are skipped when NVIDIA credentials are absent or when TESTING=1.
They do NOT use TestLLMProvider.  Fail-closed behavior is preserved.

Separation of concerns:
  - Deterministic corpus results → test_event_relationship_eval.py
  - Real NVIDIA results          → this file
  - Production pipeline merge    → test_pipeline_e2e.py / test_adversarial_clustering.py

Run with:
  $env:LLM_PROVIDER='nvidia'
  $env:TESTING='0'
  $env:TEST_MODE='0'
  pytest tests/test_nvidia_relationship_eval.py -v -s
"""
import os
import time
import pytest
from app.core.providers.llm import (
    NVIDIAProvider,
    NVIDIA_REQUEST_DEADLINE_SECONDS,
    EventRelationship,
    RelationshipResult,
    LlmUnavailableError,
    provider_is_configured,
)

# ── Skip guard ────────────────────────────────────────────────────────────────

# conftest.py sets TESTING=1 at import time, which overrides shell env vars during pytest.
# Use a separate explicit flag so the harness can be invoked from production env.
# Set NVIDIA_EVAL=1 in the shell alongside the other production env vars.
_NVIDIA_AVAILABLE = (
    os.environ.get("NVIDIA_EVAL", "0") == "1"
    and provider_is_configured("nvidia")
)

pytestmark = [
    pytest.mark.skipif(
        not _NVIDIA_AVAILABLE,
        reason=(
            "Live NVIDIA eval requires: NVIDIA_EVAL=1, LLM_PROVIDER=nvidia, "
            "TESTING=0, TEST_MODE=0, and NVIDIA_API_KEY. "
            "conftest.py forces TESTING=1 for standard test runs."
        ),
    ),
    # Real network calls; each classify_relationship call is bounded by 3
    # tenacity attempts x NVIDIAProvider's own hard per-request deadline
    # plus backoff — this MUST stay derived from that constant (see
    # test_prompt_injection_semantic.py for why a hardcoded guess here
    # previously caused this safety net to fire before the provider's own
    # bounded retry logic finished, on a genuinely slow but not hung call).
    pytest.mark.timeout(int(3 * NVIDIA_REQUEST_DEADLINE_SECONDS + 60)),
]


# ── Helper ────────────────────────────────────────────────────────────────────

def _nvidia_provider() -> NVIDIAProvider:
    from app.core.config import settings
    return NVIDIAProvider(
        api_key=settings.NVIDIA_API_KEY,
        model=settings.NVIDIA_MODEL,
        base_url=settings.NVIDIA_BASE_URL,
    )


def _eval(
    provider: NVIDIAProvider,
    article: str,
    existing_summary: str,
    context: str | None,
    expected_relationship: str,
    label: str,
) -> dict:
    """Run one classification and return a result record."""
    t0 = time.monotonic()
    try:
        result: RelationshipResult = provider.classify_relationship(
            article, existing_summary, context=context
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
    except LlmUnavailableError as exc:
        pytest.fail(f"LLM unavailable for case {label}: {exc}")

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
        "provider": "nvidia",
        "model": provider.model,
    }
    print(
        f"\n[{verdict}] {label}\n"
        f"  expected={expected_relationship}  actual={actual}\n"
        f"  reasoning: {result.reasoning[:100]}\n"
        f"  latency: {latency_ms}ms"
    )
    return record


# ── Canonical 8-case corpus ───────────────────────────────────────────────────
# Each test runs a single case.  A session-scoped fixture accumulates results
# so the summary can report overall TP/TN/FP/FN after all cases run.

_results: list[dict] = []


@pytest.fixture(scope="module")
def nvidia():
    return _nvidia_provider()


# A. SAME_EVENT — official blog + news report
def test_nvidia_A_same_event_official_and_news(nvidia):
    article = (
        "Google DeepMind has launched Gemini 3.8 Flash, designed for speed and efficiency. "
        "The model is available via the API starting today."
    )
    existing = (
        "Google DeepMind releases Gemini 3.8 Flash\n"
        "Google DeepMind released Gemini 3.8 Flash, a lightweight model for fast inference. "
        "Gemini 3.8 Flash achieves state-of-the-art performance at low latency."
    )
    r = _eval(nvidia, article, existing, context=None,
              expected_relationship=EventRelationship.SAME_EVENT, label="A-same-official-news")
    _results.append(r)
    # A FN here means the system would miss a real same-event merge
    assert r["verdict"] in ("TP", "FN"), "A same-event should not produce a FP"


# B. SAME_EVENT — different terminology
def test_nvidia_B_same_event_different_terminology(nvidia):
    article = (
        "Anthropic has unveiled Claude 4, its new large language model with 200,000-token context. "
        "The model is now available in the API."
    )
    existing = (
        "Anthropic releases Claude 4 with 200K context window\n"
        "Claude 4 is Anthropic's newest model, featuring a 200K context window and improved reasoning. "
        "Available via the Anthropic API starting today."
    )
    r = _eval(nvidia, article, existing, context=None,
              expected_relationship=EventRelationship.SAME_EVENT, label="B-same-terminology")
    _results.append(r)
    assert r["verdict"] in ("TP", "FN")


# C. UPDATE — API availability after Plus-only launch
def test_nvidia_C_update_to_same_event(nvidia):
    article = (
        "GPT-5 is now available on the OpenAI API. Developers can access GPT-5 via the API."
    )
    existing = (
        "OpenAI releases GPT-5 for ChatGPT Plus\n"
        "OpenAI released GPT-5 for ChatGPT Plus subscribers. The model is available starting today."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: model_release.",
              expected_relationship=EventRelationship.UPDATE_TO_SAME_EVENT, label="C-update-api")
    _results.append(r)
    # UPDATE should NOT merge — FP would be a false merge
    assert r["verdict"] != "FP", f"C-update must not produce a false merge: {r['reasoning']}"


# D. RELATED_EVENT — benchmark of same model
def test_nvidia_D_related_benchmark(nvidia):
    article = (
        "An independent evaluation of Grok 4 shows it tops the MATH and HumanEval benchmarks. "
        "Researchers ran 500 test cases on Grok 4."
    )
    existing = (
        "xAI releases Grok 4\n"
        "xAI releases Grok 4, the next generation of the Grok model family. It is available now."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: benchmark.",
              expected_relationship=EventRelationship.RELATED_EVENT, label="D-related-benchmark")
    _results.append(r)
    assert r["verdict"] != "FP", f"D-related must not produce a false merge: {r['reasoning']}"


# E. DIFFERENT — program-using-model vs model-release (FAIRWIND REGRESSION)
def test_nvidia_E_fairwind_regression(nvidia):
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
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: capability; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="E-fairwind-regression")
    _results.append(r)
    # This was the live false merge. Must not be FP.
    assert r["verdict"] != "FP", (
        f"FAIRWIND REGRESSION: program-using-model must not merge with model-release. "
        f"Reasoning: {r['reasoning']}"
    )


# F. DIFFERENT — same company, different products
def test_nvidia_F_same_company_different_products(nvidia):
    article = (
        "Gemini 3.8 Flash is a lightweight model designed for fast, cost-efficient inference at scale. "
        "It is a different product from Gemini 3.8 Live."
    )
    existing = (
        "Google DeepMind introduces Gemini 3.8 Live for real-time voice\n"
        "Gemini 3.8 Live is a new model optimized for real-time voice conversations with visual context."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: model_release.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="F-same-company-diff-products")
    _results.append(r)
    assert r["verdict"] != "FP", f"F must not produce a false merge: {r['reasoning']}"


# G. DIFFERENT — unrelated research mentioning same model
def test_nvidia_G_unrelated_research_mentions_model(nvidia):
    article = (
        "Researchers evaluated GPT-5, Claude 4, and Gemini 3.8 Flash on medical diagnosis tasks. "
        "They found systematic biases across all models tested."
    )
    existing = (
        "Google DeepMind releases Gemini 3.8 Flash\n"
        "Google DeepMind released Gemini 3.8 Flash, a lightweight model for fast inference. "
        "Gemini 3.8 Flash achieves state-of-the-art performance at low latency."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: research.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="G-research-mentions-model")
    _results.append(r)
    assert r["verdict"] != "FP", f"G must not produce a false merge: {r['reasoning']}"


# H. SAME_EVENT — security incident + confirmation
def test_nvidia_H_security_confirmation(nvidia):
    article = (
        "OpenAI confirmed a critical RCE vulnerability in its Discourse-based forum, exploited via "
        "libheif image processing. The issue was patched within 14 hours of the report."
    )
    existing = (
        "Researcher reports RCE vulnerability in major AI forum\n"
        "A researcher exploited a heap buffer overflow in libheif used by the OpenAI forum, "
        "gaining remote code execution and account access. The vulnerability was reported."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: security_incident; incoming article: security_incident.",
              expected_relationship=EventRelationship.SAME_EVENT, label="H-security-confirmation")
    _results.append(r)
    assert r["verdict"] in ("TP", "FN")


# ── Hard negatives (4 additional NVIDIA-validated cases) ─────────────────────

def test_nvidia_HN1_framework_integration_not_model_release(nvidia):
    """LangChain Claude 4 integration ≠ Claude 4 release. Hard negative."""
    article = (
        "LangChain 0.3.1 adds native support for Claude 4's function calling API, including "
        "structured output and tool use. This is an integration update for LangChain."
    )
    existing = (
        "Anthropic releases Claude 4 with improved function calling\n"
        "Anthropic releases Claude 4, featuring an improved function calling API with structured output."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: tool_update.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="HN1-framework-not-model")
    _results.append(r)
    assert r["verdict"] != "FP", f"HN1 must not produce a false merge: {r['reasoning']}"


def test_nvidia_HN2_funding_vs_product_launch(nvidia):
    """OpenAI funding round ≠ OpenAI GPT-6 release. Hard negative."""
    article = (
        "OpenAI secured $5 billion in new funding led by SoftBank. "
        "The round values OpenAI at $200 billion."
    )
    existing = (
        "OpenAI releases GPT-6 Astra\n"
        "OpenAI releases GPT-6 Astra, its most capable model. Available via ChatGPT and API."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: funding.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="HN2-funding-not-product")
    _results.append(r)
    assert r["verdict"] != "FP", f"HN2 must not produce a false merge: {r['reasoning']}"


def test_nvidia_HN3_different_security_incidents_same_company(nvidia):
    """Two separate Anthropic security incidents. Hard negative."""
    article = (
        "Anthropic alerted enterprise customers to a phishing campaign using spoofed "
        "Anthropic email domains. This is a separate incident."
    )
    existing = (
        "Anthropic detects unauthorized API access attempt\n"
        "Anthropic detected and blocked an unauthorized attempt to access the API using "
        "stolen credentials. No model weights or training data were accessed."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: security_incident; incoming article: security_incident.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="HN3-diff-security-incidents")
    _results.append(r)
    assert r["verdict"] != "FP", f"HN3 must not produce a false merge: {r['reasoning']}"


def test_nvidia_HN4_api_pricing_change_vs_release(nvidia):
    """GPT-5 pricing cut ≠ GPT-5 original release. Hard negative."""
    article = (
        "OpenAI announced a 50% reduction in GPT-5 API pricing, effective immediately. "
        "Input tokens now cost $0.50 per million."
    )
    existing = (
        "OpenAI releases GPT-5 for ChatGPT Plus\n"
        "OpenAI released GPT-5 for ChatGPT Plus subscribers. The model is available starting today."
    )
    r = _eval(nvidia, article, existing,
              context="Event kind context — existing event: model_release; incoming article: tool_update.",
              expected_relationship=EventRelationship.DIFFERENT_EVENT, label="HN4-pricing-not-release")
    _results.append(r)
    assert r["verdict"] != "FP", f"HN4 must not produce a false merge: {r['reasoning']}"


# ── Summary ───────────────────────────────────────────────────────────────────

def test_nvidia_corpus_summary():
    """
    Aggregate TP/TN/FP/FN after all NVIDIA cases have run.
    Reports corpus metrics without claiming global production quality.
    Does NOT assert perfect precision — reports actual results.
    """
    if not _results:
        pytest.skip("No results accumulated (run other test_nvidia_* tests first)")

    tp = sum(1 for r in _results if r["verdict"] == "TP")
    tn = sum(1 for r in _results if r["verdict"] == "TN")
    fp = sum(1 for r in _results if r["verdict"] == "FP")
    fn = sum(1 for r in _results if r["verdict"] == "FN")
    total = len(_results)
    precision = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    recall_like = tp / (tp + fn) if (tp + fn) > 0 else float("nan")

    print(f"\n{'='*60}")
    print(f"NVIDIA RELATIONSHIP EVAL — {_results[0]['model'] if _results else '?'}")
    print(f"{'='*60}")
    print(f"Cases: {total}  TP={tp}  TN={tn}  FP={fp}  FN={fn}")
    print(f"Precision (no false merges): {precision:.2f}")
    print(f"Recall-like (merges found): {recall_like:.2f}")
    print()
    for r in _results:
        verdict_str = r["verdict"]
        print(f"  [{verdict_str}] {r['label']:40} {r['expected']:25} → {r['actual']:25} {r['latency_ms']}ms")
    print(f"{'='*60}")

    # Hard constraint: zero false merges. FN is acceptable but must be tracked.
    assert fp == 0, (
        f"FALSE MERGES detected in NVIDIA eval: "
        + ", ".join(r["label"] for r in _results if r["verdict"] == "FP")
    )

    # Warn (not fail) on false negatives so CI does not hide them
    if fn > 0:
        missed = [r["label"] for r in _results if r["verdict"] == "FN"]
        print(f"WARNING: {fn} missed merge(s) (FN): {missed}")
