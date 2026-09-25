"""
LLM usage ledger: one JSON line per provider request.

Records provider, model, operation, the article or event it was for, input
and output tokens, latency and success. Never the prompt, the response, the
API key or an exception message (provider errors can echo request data);
only the exception type.

A JSON-lines file, not a table: ingestion holds SQLite write transactions
while it calls the provider, and a ledger write must never contend with them.
`python manage_sources.py llm-usage` summarizes it.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_subject: contextvars.ContextVar[str] = contextvars.ContextVar("llm_subject", default="")
_lock = threading.Lock()

# Structured-output model -> operation name shown in the ledger.
OPERATIONS = {
    "EventClassification": "classify_event",
    "SourceGroundedSummary": "summarize_event",
    "RelationshipResult": "classify_relationship",
    "CategoryBatch": "classify_categories_batch",
}


def ledger_path() -> str:
    configured = os.environ.get("LLM_USAGE_LOG")
    if configured:
        return configured
    backend = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend, "logs", "llm_usage.jsonl")


@contextlib.contextmanager
def llm_subject(subject: str) -> Iterator[None]:
    """Attribute provider calls in this block to an article, event or batch id."""
    token = _subject.set(str(subject or ""))
    try:
        yield
    finally:
        _subject.reset(token)


def operation_for(model_cls) -> str:
    return OPERATIONS.get(getattr(model_cls, "__name__", ""), getattr(model_cls, "__name__", "unknown"))


def record(
    *,
    provider: str,
    model: str,
    operation: str,
    started: float,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    success: bool,
    error_type: str = "",
) -> None:
    row = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "operation": operation,
        "subject": _subject.get(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "success": success,
        "error_type": error_type,
    }
    logger.info(
        "llm_usage provider=%s model=%s operation=%s subject=%s in=%s out=%s latency_ms=%s success=%s",
        provider, model, operation, row["subject"], input_tokens, output_tokens, row["latency_ms"], success,
    )
    try:
        path = ledger_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        logger.warning("llm_usage ledger write failed")


def usage_tokens(usage) -> tuple[Optional[int], Optional[int]]:
    """(input, output) from an OpenAI-style or Anthropic-style usage object."""
    if usage is None:
        return None, None
    prompt = getattr(usage, "prompt_tokens", None)
    if prompt is None:
        prompt = getattr(usage, "input_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if completion is None:
        completion = getattr(usage, "output_tokens", None)
    return prompt, completion


def read_ledger(since: Optional[datetime] = None) -> list[dict]:
    path = ledger_path()
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if since is not None:
                try:
                    if datetime.fromisoformat(row.get("at", "")) < since:
                        continue
                except ValueError:
                    continue
            rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    by_operation: dict[str, dict] = {}
    for row in rows:
        entry = by_operation.setdefault(
            row.get("operation", "unknown"),
            {"requests": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0},
        )
        entry["requests"] += 1
        entry["failed"] += 0 if row.get("success") else 1
        entry["input_tokens"] += row.get("input_tokens") or 0
        entry["output_tokens"] += row.get("output_tokens") or 0
        entry["latency_ms"] += row.get("latency_ms") or 0
    return by_operation
