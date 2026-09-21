"""
Process runtime flags.

Python treats any non-empty string as true, so TESTING=0 would otherwise
keep the app in test mode. Only 1/true/yes/on enable a flag.
"""
from __future__ import annotations

import os


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def is_test_runtime() -> bool:
    """True when pytest/TEST_MODE requested the deterministic LLM and no scheduler."""
    if env_flag("TESTING"):
        return True
    from app.core.config import settings
    return bool(settings.TEST_MODE)
