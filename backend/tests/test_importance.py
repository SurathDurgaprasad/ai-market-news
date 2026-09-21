"""Deterministic importance gates (no live LLM)."""
from app.core.importance import is_obvious_noise, normalize_importance_score


def test_clickbait_is_obvious_noise():
    assert is_obvious_noise(
        "Top 10 AI tools you must try this weekend",
        "Number 4 will shock you.",
    )


def test_real_release_is_not_noise():
    assert not is_obvious_noise(
        "OpenAI Releases GPT-5",
        "Today we are releasing GPT-5, our most capable model yet.",
    )


def test_normalize_importance_score():
    assert normalize_importance_score(0) is None
    assert normalize_importance_score(None) is None
    assert normalize_importance_score("nope") is None
    assert normalize_importance_score(50) == 50
    assert normalize_importance_score(101) == 100
    assert normalize_importance_score(-5) == 1
    assert normalize_importance_score(1) == 1
    assert normalize_importance_score(100) == 100
