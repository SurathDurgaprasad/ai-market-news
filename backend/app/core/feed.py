"""
Current-week feed scope.

The dashboard answers "what happened in AI this week", newest first.
Importance does not change order. Non-AI items from broad feeds stay out
of that feed; primary/research sources stay because they are curated.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

_PROMO = re.compile(
    r"\b("
    r"exhibitor program|founder summit|"
    r"pass(?:es)? discount|discount(?:s)? on .{0,48}passes"
    r")\b",
    re.IGNORECASE,
)

# Word-boundary signals that the item is an AI development. Primary and
# research sources skip this check. "model" is included because hardware
# and release headlines often say "model" without the letters "AI".
_AI_SIGNAL = re.compile(
    r"\b("
    r"a\.?i\.?|artificial intelligence|machine learning|deep learning|"
    r"llms?|gpt(?:-\d+|\d+)?|claude|gemini|llama|mistral|deepseek|grok|"
    r"openai|anthropic|deepmind|neural|transformers?|gpus?|inference|"
    r"robots?|robotics|agents?|benchmarks?|datasets?|multimodal|diffusion|"
    r"generative|foundation models?|open[- ]weights?|tokenizers?|"
    r"bedrock|cuda|nvidia|hugging\s?face|langchain|"
    r"fine-?tun\w*|checkpoints?|parameters?|mixture-of-experts?|"
    r"algorithms?|chatbots?|autonomous|computer vision|facial recognition|"
    r"copilots?|language models?|surveillance|models?"
    r")\b",
    re.IGNORECASE,
)


def current_week_start(now: Optional[datetime] = None) -> datetime:
    """Monday 00:00 UTC of the ISO week containing `now`."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=start.weekday())


def is_feed_in_scope(
    headline: Optional[str],
    summary: Optional[str] = None,
    tier: Optional[str] = None,
) -> bool:
    """
    True when a canonical event belongs on the intelligence feed.

    Curated primary and research sources are in scope. Secondary and
    community items must actually be about AI. Outlet self-promotion
    (conference passes, exhibitor programs) is out of scope at every tier.
    """
    title = headline or ""
    if _PROMO.search(title):
        return False
    kind = (tier or "").strip().lower()
    if kind in {"primary", "research"}:
        return True
    text = f"{title}\n{summary or ''}"
    return _AI_SIGNAL.search(text) is not None
