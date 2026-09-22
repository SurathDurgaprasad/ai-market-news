"""
NVDA-01 (docs/RED_TEAM_REPORT.md) was fixed for NVIDIAProvider first,
since that's the actual configured production provider and the one that
hung in a live test. This file proves the same fix was applied
consistently to OpenAIProvider and AnthropicProvider — the provider
abstraction should behave uniformly, not leave two of its three real
implementations with the original unbounded-timeout weakness just
because they weren't the one that happened to get red-teamed.

Same technique as test_nvidia_timeout_bound.py: a fake httpx transport
that drip-feeds response bytes with gaps individually under the client's
nominal timeout, proving the client-level `timeout=` alone does not
bound total call duration, then proving the hard per-request deadline
does.
"""
import time

import httpx
import pytest

from app.core.providers.llm import (
    OpenAIProvider,
    AnthropicProvider,
    ProviderRequestTimeout,
    LlmUnavailableError,
)
from tests.test_nvidia_timeout_bound import TrickleTransport


def test_openai_provider_enforces_hard_deadline_against_trickling_transport():
    trickling_http_client = httpx.Client(
        transport=TrickleTransport(chunk_gap=0.05, chunks=50),
        timeout=30.0,  # generous per-phase timeout that would never fire on its own
    )
    provider = OpenAIProvider(
        api_key="test-key",
        http_client=trickling_http_client,
        request_deadline_seconds=0.5,
    )

    start = time.monotonic()
    # As of SCHED-OUTAGE-01 (docs/RED_TEAM_REPORT.md), the raw
    # ProviderRequestTimeout no longer escapes the public classify_event()
    # — _unavailable_on_any_error normalizes it to LlmUnavailableError so
    # pipeline.py's LlmUnavailableError handling (not a generic except
    # that would silently misclassify an outage) is what receives it.
    with pytest.raises(LlmUnavailableError) as exc_info:
        provider.classify_event("test article content")
    assert isinstance(exc_info.value.__cause__, ProviderRequestTimeout)
    elapsed = time.monotonic() - start

    # classify_event has its own tenacity retry (3 attempts, backoff) —
    # same shape as NVIDIAProvider's, so the bound is generous but finite.
    assert elapsed < 15.0, f"OpenAIProvider.classify_event took {elapsed:.2f}s — not bounded"


def test_anthropic_provider_enforces_hard_deadline_against_trickling_transport():
    anthropic = pytest.importorskip("anthropic")
    # The installed anthropic SDK (1.7.0) is built on `httpx2`, a separate
    # package from `httpx` (same author/shape, different module) — it
    # rejects a raw httpx.Client outright ("this SDK uses httpx2"). Same
    # TrickleTransport technique, built on whichever transport module the
    # installed SDK actually accepts, discovered by construction rather
    # than assumed.
    try:
        import httpx2 as anthropic_httpx
    except ImportError:
        anthropic_httpx = httpx

    class _AnthropicTrickleTransport(anthropic_httpx.BaseTransport):
        def __init__(self, chunk_gap: float, chunks: int):
            self.chunk_gap = chunk_gap
            self.chunks = chunks

        def handle_request(self, request):
            def body():
                for _ in range(self.chunks):
                    time.sleep(self.chunk_gap)
                    yield b" "
            return anthropic_httpx.Response(200, content=body())

    trickling_http_client = anthropic_httpx.Client(
        transport=_AnthropicTrickleTransport(chunk_gap=0.05, chunks=50),
        timeout=30.0,
    )
    provider = AnthropicProvider(
        api_key="test-key",
        http_client=trickling_http_client,
        request_deadline_seconds=0.5,
    )
    assert provider.client is not None, "AnthropicProvider did not construct a client with a fake api key"

    start = time.monotonic()
    with pytest.raises(LlmUnavailableError) as exc_info:
        provider.classify_event("test article content")
    assert isinstance(exc_info.value.__cause__, ProviderRequestTimeout)
    elapsed = time.monotonic() - start

    # AnthropicProvider.classify_event now has the same tenacity retry
    # shape as NVIDIA/OpenAI (added alongside SCHED-OUTAGE-01 for
    # consistency — it previously had none at all), so the bound is
    # generous but finite, same as the OpenAI case above.
    assert elapsed < 15.0, f"AnthropicProvider.classify_event took {elapsed:.2f}s — not bounded"
