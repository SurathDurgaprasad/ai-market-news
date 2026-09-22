"""
Root-cause investigation and regression coverage for NVDA-01
(docs/RED_TEAM_REPORT.md): a live NVIDIA-provider test hung for 8+
minutes despite NVIDIAProvider constructing its openai client with
`timeout=90.0`.

Traced request path: pytest -> NVIDIAProvider.classify_event (tenacity
@retry, 3 attempts) -> NVIDIAProvider._complete_json (loops up to 4 JSON
modes) -> NVIDIAProvider._create_completion -> openai.OpenAI.chat.
completions.create (its OWN internal retry, default max_retries=2,
independent of and stacked on top of our tenacity retry) -> httpx.Client
request, timeout=httpx.Timeout(90.0) (connect=read=write=pool=90.0 each).

Root cause: httpx's "read" timeout bounds the gap BETWEEN successive
chunks of a response, not the response's total wall-clock duration. A
transport (or a real server/proxy) that drip-feeds bytes with any gap
under 90s never trips it, however long the request runs in total. This
is proven deterministically below with a fake transport, without
needing a real multi-minute wait. On top of that, openai's own
max_retries=2 and our tenacity's 3 attempts multiply the number of raw
HTTP attempts a single logical call can make, each individually subject
to the same unbounded-total-time behavior.

Fix: NVIDIAProvider now wraps each raw HTTP attempt in a hard wall-clock
deadline (ProviderRequestTimeout, enforced via a worker-thread future
with `.result(timeout=...)`), independent of httpx's per-phase timeouts.
This bounds the CALL that application code is waiting on; it does not
retroactively cancel the abandoned in-flight socket read (Python cannot
forcibly kill a thread), which is a documented residual limitation, not
a claim of full resource cleanup.
"""
import time

import httpx
import pytest

from app.core.providers.llm import (
    NVIDIAProvider,
    ProviderRequestTimeout,
    LlmUnavailableError,
    nvidia_error_is_retryable,
)


class TrickleTransport(httpx.BaseTransport):
    """
    Drip-feeds response bytes with a fixed gap between chunks, each gap
    individually under the client's configured read timeout, so no
    single httpx-level timeout ever fires — while the TOTAL elapsed time
    across all chunks can exceed any nominal "timeout" the caller set.
    """

    def __init__(self, chunk_gap: float, chunks: int):
        self.chunk_gap = chunk_gap
        self.chunks = chunks

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        def body():
            for _ in range(self.chunks):
                time.sleep(self.chunk_gap)
                yield b" "

        return httpx.Response(200, content=body())


def test_httpx_read_timeout_does_not_bound_total_wall_clock_time():
    """
    Root-cause proof, independent of our provider code: a bare httpx
    client with timeout=0.5s, talking to a transport that trickles 5
    chunks with a 0.3s gap each (each gap comfortably under 0.5s), takes
    ~1.5s total — more than 3x the nominal timeout. This is the exact
    mechanism that let the real NVIDIA call run past its configured 90s
    "timeout" for 8+ minutes.
    """
    client = httpx.Client(transport=TrickleTransport(chunk_gap=0.3, chunks=5), timeout=0.5)
    start = time.monotonic()
    response = client.get("http://fake.invalid/v1/chat/completions")
    elapsed = time.monotonic() - start
    response.read()  # force full consumption of the trickle body
    total_elapsed = time.monotonic() - start

    assert total_elapsed > 1.0, (
        f"Expected the trickle to exceed the nominal 0.5s timeout (proving "
        f"read-timeout is per-chunk, not total), but it took {total_elapsed:.2f}s"
    )


def test_nvidia_provider_enforces_hard_deadline_against_trickling_transport():
    """
    The actual fix: NVIDIAProvider must not let a single raw HTTP attempt
    run past its configured hard deadline, even when httpx's own
    connect/read/write/pool timeouts would never fire (trickling
    transport, 50 chunks x 0.05s gap = 2.5s of trickle, each gap far
    under any per-phase httpx timeout).
    """
    trickling_http_client = httpx.Client(
        transport=TrickleTransport(chunk_gap=0.05, chunks=50),
        timeout=30.0,  # generous per-phase timeout that would never fire on its own
    )
    provider = NVIDIAProvider(
        api_key="test-key",
        base_url="http://fake.invalid/v1",
        http_client=trickling_http_client,
        request_deadline_seconds=0.5,
    )

    start = time.monotonic()
    with pytest.raises(ProviderRequestTimeout):
        provider._create_completion(
            messages=[{"role": "user", "content": "hi"}],
            schema={},
            mode="plain",
        )
    elapsed = time.monotonic() - start

    # Bounded near the configured hard deadline (0.5s), nowhere near the
    # 2.5s of total trickle time the transport is capable of producing.
    assert elapsed < 1.5, (
        f"Hard deadline did not bound the call: took {elapsed:.2f}s "
        f"against a 0.5s deadline"
    )


def test_provider_request_timeout_is_classified_retryable():
    """
    A hard-deadline timeout must be treated the same as any other
    transient network timeout by the existing retry classifier, so
    tenacity's bounded outer retry (not a second unbounded wait) governs
    what happens next.
    """
    assert nvidia_error_is_retryable(ProviderRequestTimeout("deadline exceeded"))


def test_classify_event_raises_bounded_error_not_unbounded_hang():
    """
    End-to-end through the public classify_event() entrypoint (the exact
    method the original 8-minute hang occurred in), with tenacity retries
    disabled by exhausting them quickly via a short deadline: the whole
    call must still return control to the caller in bounded time instead
    of hanging.
    """
    trickling_http_client = httpx.Client(
        transport=TrickleTransport(chunk_gap=0.05, chunks=50),
        timeout=30.0,
    )
    provider = NVIDIAProvider(
        api_key="test-key",
        base_url="http://fake.invalid/v1",
        http_client=trickling_http_client,
        request_deadline_seconds=0.3,
    )

    start = time.monotonic()
    # classify_event catches parse/validation errors and returns None; a
    # ProviderRequestTimeout is retryable so tenacity retries it up to 3
    # attempts (bounded) before propagating. As of SCHED-OUTAGE-01 (see
    # docs/RED_TEAM_REPORT.md), the public classify_event() no longer lets
    # that raw ProviderRequestTimeout escape — _unavailable_on_any_error
    # normalizes it to LlmUnavailableError so pipeline.py's existing
    # `except LlmUnavailableError` handling (not a generic except that
    # would silently misclassify an outage as an ordinary rejected
    # article) is what actually receives it. The original cause is still
    # reachable via __cause__ for diagnosis.
    with pytest.raises(LlmUnavailableError) as exc_info:
        provider.classify_event("test article content")
    assert isinstance(exc_info.value.__cause__, ProviderRequestTimeout)
    elapsed = time.monotonic() - start

    # 3 tenacity attempts x (~0.3s deadline + backoff) — generous upper
    # bound that is still an order of magnitude below "minutes".
    assert elapsed < 15.0, f"classify_event took {elapsed:.2f}s — not bounded"
