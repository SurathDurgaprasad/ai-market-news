import os
from app.core.providers.llm import (
    resolve_llm_mode,
    get_llm_provider,
    TestLLMProvider,
    ProductionLLMProvider,
    NVIDIAProvider,
    OpenAIProvider,
    AnthropicProvider,
    FailClosedLLMProvider,
    LlmUnavailableError,
    LLM_TEST,
    LLM_PRODUCTION,
    LLM_UNAVAILABLE,
)
from app.core.runtime import env_flag, is_test_runtime
from app.core.pipeline import IntelligencePipeline
from app.core.parser import ArticleData
from app.models.source import Source
from app.models.event import Event


def _clear_llm_keys(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", None)
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", None)
    monkeypatch.setattr("app.core.config.settings.ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_env_flag_treats_zero_as_false():
    assert env_flag("MISSING_FLAG_XYZ") is False
    os.environ["TMP_FLAG_TEST"] = "0"
    try:
        assert env_flag("TMP_FLAG_TEST") is False
        os.environ["TMP_FLAG_TEST"] = "1"
        assert env_flag("TMP_FLAG_TEST") is True
        os.environ["TMP_FLAG_TEST"] = "false"
        assert env_flag("TMP_FLAG_TEST") is False
        os.environ["TMP_FLAG_TEST"] = "true"
        assert env_flag("TMP_FLAG_TEST") is True
    finally:
        os.environ.pop("TMP_FLAG_TEST", None)


def test_testing_1_forces_test_provider(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    assert resolve_llm_mode() == LLM_TEST
    assert isinstance(get_llm_provider(), TestLLMProvider)


def test_testing_0_is_not_test_runtime(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    assert is_test_runtime() is False


def test_test_mode_settings_forces_test(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", True)
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-present")
    assert resolve_llm_mode() == LLM_TEST
    assert isinstance(get_llm_provider(), TestLLMProvider)


def test_explicit_test_env_wins_over_key(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-present")
    assert resolve_llm_mode("test") == LLM_TEST


def test_production_nvidia_when_key_and_not_testing(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    _clear_llm_keys(monkeypatch)
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", "nvapi-not-a-real-key")
    assert resolve_llm_mode() == LLM_PRODUCTION
    provider = get_llm_provider()
    assert isinstance(provider, NVIDIAProvider)
    assert not isinstance(provider, TestLLMProvider)


def test_production_openai_when_explicitly_selected(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "openai")
    _clear_llm_keys(monkeypatch)
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-not-a-real-key")
    assert resolve_llm_mode() == LLM_PRODUCTION
    provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)
    assert isinstance(provider, ProductionLLMProvider)
    assert not isinstance(provider, TestLLMProvider)


def test_production_anthropic_when_sdk_missing_is_fail_closed(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "anthropic")
    _clear_llm_keys(monkeypatch)
    monkeypatch.setattr("app.core.config.settings.ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    provider = get_llm_provider()
    assert isinstance(provider, (AnthropicProvider, FailClosedLLMProvider))
    assert not isinstance(provider, TestLLMProvider)


def test_nvidia_selected_does_not_fall_back_to_openai_key(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    _clear_llm_keys(monkeypatch)
    monkeypatch.setattr("app.core.config.settings.OPENAI_API_KEY", "sk-present")
    assert resolve_llm_mode() == LLM_UNAVAILABLE
    provider = get_llm_provider()
    assert isinstance(provider, FailClosedLLMProvider)
    assert not isinstance(provider, TestLLMProvider)
    assert not isinstance(provider, NVIDIAProvider)


def test_missing_key_on_production_path_is_unavailable(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    _clear_llm_keys(monkeypatch)
    assert resolve_llm_mode() == LLM_UNAVAILABLE
    provider = get_llm_provider()
    assert isinstance(provider, FailClosedLLMProvider)
    assert not isinstance(provider, TestLLMProvider)
    try:
        provider.classify_event("any")
        assert False, "FailClosedLLMProvider must raise"
    except LlmUnavailableError:
        pass


def test_pipeline_production_without_key_does_not_emit_testcorp(db_session, monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "nvidia")
    _clear_llm_keys(monkeypatch)

    pipeline = IntelligencePipeline(db_session)
    assert isinstance(pipeline.llm, FailClosedLLMProvider)
    source_id = db_session.query(Source).first().id
    article = ArticleData(
        title="Real looking headline about a model release",
        url="https://openai.com/blog/real",
        content="This article body is long enough to pass the minimum content gate for ingestion.",
    )
    try:
        event = pipeline.process_article(article, source_id)
        assert event is None
    except LlmUnavailableError:
        pass
    assert db_session.query(Event).count() == 0
    headlines = [e.headline for e in db_session.query(Event).all()]
    assert "Mock Headline for TestCorp" not in headlines


def test_unknown_provider_is_fail_closed(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("app.core.config.settings.TEST_MODE", False)
    monkeypatch.setattr("app.core.config.settings.LLM_PROVIDER", "acme-cloud")
    _clear_llm_keys(monkeypatch)
    assert resolve_llm_mode() == LLM_UNAVAILABLE
    provider = get_llm_provider()
    assert isinstance(provider, FailClosedLLMProvider)
    assert not isinstance(provider, TestLLMProvider)
