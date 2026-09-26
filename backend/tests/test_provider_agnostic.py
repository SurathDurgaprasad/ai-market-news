"""
PROVIDER-AGNOSTIC-01 (docs/security-findings.md): the LLM architecture must
be genuinely provider-agnostic across NVIDIA, OpenAI, Anthropic, and
Bedrock, with the pipeline depending only on the LLMProvider contract and
never seeing a raw provider-specific exception.

This file covers exactly the regression list from the operating brief
that isn't already covered elsewhere in the suite:
  - OpenAI provider can initialize with its configuration.
  - Bedrock errors are normalized (the one provider with no existing
    coverage before this task).
  - Missing credentials fail clearly, for all four providers.
  - Unknown provider fails clearly.
  - Pipeline behavior is identical regardless of provider.
  - Provider-specific exceptions never leak through the application
    boundary — extended here to cover Bedrock specifically via
    botocore.stub.Stubber (simulates real botocore ClientError responses
    without live AWS access or network calls).

Already covered elsewhere, referenced rather than duplicated:
  - OpenAI/NVIDIA/Anthropic timeout -> normalized error mapping:
    test_nvidia_timeout_bound.py, test_provider_timeout_bound_openai_anthropic.py
  - NVIDIA behavior unchanged (mocked, real SDK object):
    test_nvidia_provider.py (23 tests, all passing after this refactor)
  - LLM unavailable distinguishable from zero events:
    test_scheduler_provider_outage.py (SCHED-OUTAGE-01)
  - Retry/deadline bounded: test_nvidia_timeout_bound.py
"""
import pytest

from app.core.providers.llm import (
    NVIDIAProvider,
    OpenAIProvider,
    AnthropicProvider,
    BedrockProvider,
    FailClosedLLMProvider,
    LlmUnavailableError,
    get_llm_provider,
)
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.core.ai_processor import EventClassification
from app.models.source import Source


# ── OpenAI initializes with its own configuration ──────────────────────────

def test_openai_provider_initializes_with_configuration():
    provider = OpenAIProvider(api_key="sk-test-key", model="gpt-4o-mini")
    assert provider.client is not None
    assert provider.model == "gpt-4o-mini"
    assert provider.request_deadline_seconds > 0
    assert provider.operation_deadline_seconds > 0


def test_openai_provider_has_no_client_without_a_key(monkeypatch):
    """
    OpenAIProvider(api_key=None, ...) falls back to settings.OPENAI_API_KEY
    (`key = api_key or settings.OPENAI_API_KEY` — intentional: an explicit
    key always wins, otherwise fall back to configured settings, same
    pattern as NVIDIAProvider/AnthropicProvider). That fallback means this
    test's "no key -> no client" precondition depends on the AMBIENT
    environment/registry having no OPENAI_API_KEY, which stopped being
    true the moment a real key was added to this machine's Windows User
    environment for live validation. Explicitly clearing both
    settings.OPENAI_API_KEY and the env var guarantees this test's own
    precondition regardless of what's ambiently configured on the machine
    running it — the same fix class as the credential-clearing pattern
    already established in test_llm_env.py's _clear_llm_keys().
    """
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider(api_key=None, model="gpt-4o-mini")
    assert provider.client is None
    with pytest.raises(LlmUnavailableError):
        provider.classify_event("anything")


# ── Bedrock errors are normalized (the one provider with zero prior
# coverage) — via botocore.stub.Stubber, a real boto3 testing mechanism
# that simulates authentic botocore ClientError responses without any
# live AWS access or network call. ─────────────────────────────────────────

def _stubbed_bedrock_provider(error_code: str, http_status: int = 400):
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber

    provider = BedrockProvider(
        model="anthropic.claude-3-sonnet-20240229-v1:0",
        region_name="us-east-1",
        request_deadline_seconds=5.0,
        operation_deadline_seconds=8.0,
    )
    assert provider.client is not None, "BedrockProvider did not construct a client"
    stubber = Stubber(provider.client)
    # Enough stubbed responses to cover every tenacity retry attempt.
    for _ in range(3):
        stubber.add_client_error("invoke_model", service_error_code=error_code, http_status_code=http_status)
    stubber.activate()
    return provider, stubber


def test_bedrock_throttling_error_is_normalized_to_llm_unavailable():
    """
    A raw botocore ThrottlingException (dynamically-named subclass of
    ClientError — see _botocore_client_error_code's docstring for why
    that distinction mattered) must never reach the caller as itself.
    """
    provider, stubber = _stubbed_bedrock_provider("ThrottlingException", http_status=429)
    with stubber:
        with pytest.raises(LlmUnavailableError) as exc_info:
            provider.classify_event("test article content")
    # The original botocore error is preserved for diagnosis, not swallowed.
    assert "Throttling" in str(exc_info.value) or "ThrottlingException" in type(exc_info.value.__cause__).__name__


def test_bedrock_access_denied_is_normalized_to_llm_unavailable():
    """A fatal auth-shaped error (bad/missing AWS permissions) must also
    normalize cleanly, not crash with a raw botocore exception."""
    provider, stubber = _stubbed_bedrock_provider("AccessDeniedException", http_status=403)
    with stubber:
        with pytest.raises(LlmUnavailableError):
            provider.classify_event("test article content")


def test_bedrock_no_credentials_is_normalized_to_llm_unavailable():
    """
    The actual expected real-world failure mode in an environment with no
    AWS credentials configured at all — botocore raises NoCredentialsError
    before ever reaching the network.
    """
    provider = BedrockProvider(
        model="anthropic.claude-3-sonnet-20240229-v1:0",
        region_name="us-east-1",
        request_deadline_seconds=5.0,
        operation_deadline_seconds=8.0,
    )
    # A client constructed with no credentials at all in the environment
    # (no env vars, no ~/.aws/credentials, no IAM role) raises
    # NoCredentialsError on the first real call. We can't guarantee this
    # sandbox has zero AWS credential sources, so simulate the same
    # failure via Stubber for a deterministic, environment-independent test.
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import Stubber
    from botocore.exceptions import NoCredentialsError

    stubber = Stubber(provider.client)
    stubber.activate()
    # Stubber doesn't have a direct NoCredentialsError helper; patch the
    # underlying call to raise it directly, exercising the exact same
    # _unavailable_on_any_error normalization path.
    def _raise_no_creds(*a, **k):
        raise NoCredentialsError()
    provider.client.invoke_model = _raise_no_creds

    with pytest.raises(LlmUnavailableError):
        provider.classify_event("test article content")


def test_bedrock_provider_without_boto3_or_config_is_cleanly_unavailable():
    """No model/region configured at all — must fail at construction, not
    with an obscure AttributeError deep inside a later call."""
    provider = BedrockProvider(model=None, region_name=None)
    assert provider.client is None
    with pytest.raises(LlmUnavailableError):
        provider.classify_event("anything")


# ── Missing credentials fail clearly, for all four providers ──────────────

@pytest.mark.parametrize("provider_name,clear_attrs", [
    ("nvidia", ["NVIDIA_API_KEY"]),
    ("openai", ["OPENAI_API_KEY"]),
    ("anthropic", ["ANTHROPIC_API_KEY"]),
    ("bedrock", ["BEDROCK_MODEL_ID", "AWS_REGION"]),
])
def test_missing_credentials_fail_clearly(monkeypatch, provider_name, clear_attrs):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", provider_name)
    for key in ("NVIDIA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "BEDROCK_MODEL_ID", "AWS_REGION"):
        monkeypatch.setattr(f"app.core.config.settings.{key}", None)
        monkeypatch.delenv(key, raising=False)

    provider = get_llm_provider(env=provider_name)
    assert isinstance(provider, FailClosedLLMProvider), (
        f"{provider_name} with no credentials must fail closed, got {type(provider).__name__}"
    )
    with pytest.raises(LlmUnavailableError):
        provider.classify_event("anything")


# ── Unknown provider fails clearly ─────────────────────────────────────────

def test_unknown_provider_fails_clearly(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "some-made-up-provider")
    # provider_is_configured() returns False for anything it doesn't
    # recognize, so resolve_llm_mode() already reports LLM_UNAVAILABLE —
    # get_llm_provider() must still return a clean FailClosedLLMProvider,
    # not raise a KeyError or fall through to some default provider.
    provider = get_llm_provider()
    assert isinstance(provider, FailClosedLLMProvider)
    with pytest.raises(LlmUnavailableError):
        provider.classify_event("anything")


# ── Pipeline behavior is identical regardless of provider ─────────────────

def _classification_fixture() -> EventClassification:
    return EventClassification(
        tags=["LLM"],
        categories=["Model Release"],
        entities=["ExampleCorp"],
        primary_entities=["ExampleCorp"],
        mentioned_entities=[],
        event_kind="model_release",
        technical_change_scope="product",
        security_impact="none",
        importance_score=65,
        importance_reasoning="A routine model release.",
    )


def _summary_fixture():
    from app.core.ai_processor import SourceGroundedSummary
    return SourceGroundedSummary(
        headline="ExampleCorp releases ExampleModel",
        short_summary="ExampleCorp released ExampleModel today with new capabilities.",
        what_changed="Released ExampleModel with improved reasoning.",
        citations=["ExampleCorp released ExampleModel today with new capabilities."],
    )


def _optional_sdk(module: str):
    """anthropic and boto3 are optional installs (see requirements.txt)."""
    import importlib.util

    return pytest.mark.skipif(importlib.util.find_spec(module) is None, reason=f"{module} not installed")


@pytest.mark.parametrize("provider_factory", [
    pytest.param(lambda: NVIDIAProvider(api_key="fake", model="fake-model"), id="nvidia"),
    pytest.param(lambda: OpenAIProvider(api_key="fake", model="fake-model"), id="openai"),
    pytest.param(lambda: AnthropicProvider(api_key="fake", model="fake-model"), id="anthropic",
                 marks=_optional_sdk("anthropic")),
    pytest.param(lambda: BedrockProvider(model="fake-model", region_name="us-east-1"), id="bedrock",
                 marks=_optional_sdk("boto3")),
])
def test_pipeline_behavior_identical_regardless_of_provider(db_session, provider_factory):
    """
    All four real provider classes share the exact same `_complete_json(
    system, user, model_cls)` signature and contract (this is what makes
    the pipeline provider-agnostic in practice, not just in principle) —
    patch it uniformly on each provider instance and confirm
    IntelligencePipeline.process_article() produces an IDENTICAL resulting
    Event regardless of which concrete provider class is plugged in.
    """
    provider = provider_factory()
    assert provider.client is not None, f"{type(provider).__name__} did not construct a client"

    def fake_complete_json(system, user, model_cls):
        if model_cls is EventClassification:
            return _classification_fixture()
        return _summary_fixture()

    provider._complete_json = fake_complete_json

    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = provider

    source = Source(name="Test Source", url="https://example.com/rss", type="rss")
    db_session.add(source)
    db_session.commit()

    article = ArticleData(
        title="ExampleCorp releases ExampleModel",
        url="https://example.com/examplemodel",
        content="ExampleCorp released ExampleModel today with new capabilities. " * 2,
        published_at=None,
    )

    event = pipeline.process_article(article, source.id)

    assert event is not None, f"{type(provider).__name__}: pipeline produced no event"
    assert event.headline == "ExampleCorp releases ExampleModel"
    assert event.importance_score == 65
    assert "ExampleCorp" in (event.entities or [])
    reasoning = event.importance_reasoning or {}
    assert reasoning.get("event_kind") == "model_release"
