"""
Safe production-path check: never emits TestCorp events without TEST_MODE.

Run from backend/:
    python validate_production_path.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.core.providers.llm import (
    resolve_llm_mode,
    get_llm_provider,
    TestLLMProvider,
    ProductionLLMProvider,
    NVIDIAProvider,
    OpenAIProvider,
    FailClosedLLMProvider,
    LLM_UNAVAILABLE,
    LLM_PRODUCTION,
    LLM_TEST,
    configured_llm_provider_name,
)
from app.core.runtime import is_test_runtime
from app.core.scheduler import IngestionScheduler


def main() -> None:
    mode = resolve_llm_mode()
    provider = get_llm_provider()
    name = configured_llm_provider_name()
    print(f"test_runtime={is_test_runtime()}")
    print(f"llm_mode={mode}")
    print(f"llm_provider={name}")
    print(f"provider={type(provider).__name__}")

    if mode == LLM_TEST:
        assert isinstance(provider, TestLLMProvider)
        print("STATE: test runtime. TestLLMProvider is expected.")
        print("REAL LLM PATH: UNVERIFIED (this process is in test runtime).")
        return

    if mode == LLM_UNAVAILABLE:
        assert isinstance(provider, FailClosedLLMProvider)
        assert not isinstance(provider, TestLLMProvider)
        result = IngestionScheduler().run_ingestion_cycle()
        print(f"scheduler_result={result}")
        if result and result.get("blocked") == "llm_unavailable":
            print(f"STATE: production runtime, no usable credentials for LLM_PROVIDER={name}.")
            print("Scheduler did not fetch and did not emit mock events.")
            print("REAL LLM PATH: UNVERIFIED (credential absent).")
            return
        print("FAILED: expected scheduler to block with llm_unavailable")
        sys.exit(1)

    if mode == LLM_PRODUCTION:
        assert not isinstance(provider, TestLLMProvider)
        if name == "nvidia":
            assert isinstance(provider, NVIDIAProvider)
        elif name == "openai":
            assert isinstance(provider, (OpenAIProvider, ProductionLLMProvider))
        print("STATE: production LLM configured.")
        print("This script does not spend tokens. Run validate_nvidia_live.py for a real ingest.")
        return

    print(f"FAILED: unexpected mode {mode}")
    sys.exit(1)


if __name__ == "__main__":
    main()
