"""
Cost controls around paid provider calls.

Live: the OpenAI account ran out of quota. Each 429 `insufficient_quota` was
retried by the SDK (2 logical requests became 6 HTTP attempts) and would
have been retried again by tenacity and by the backfill's own retry, none of
which can succeed. Separately, a test run with keys in the environment made
real provider calls. None of these tests touch the network or the
production database.
"""
import json
import os
import uuid

import pytest

from app.core.providers.llm import (
    LlmUnavailableError,
    OpenAIProvider,
    ProviderQuotaExhausted,
    TestLLMProvider,
    is_quota_exhausted,
    nvidia_error_is_retryable,
)


class RateLimitError(Exception):
    """Shaped like openai.RateLimitError: status 429, error code in `code` and `body`."""

    status_code = 429

    def __init__(self, code):
        super().__init__(f"Error code: 429 - {{'error': {{'code': '{code}'}}}}")
        self.code = code
        self.body = {"code": code, "type": code}


def _client_raising(error, calls):
    class Completions:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs.get("model"))
            raise error

    class Chat:
        completions = Completions()

    class Client:
        chat = Chat()

    return Client()


def test_exhausted_quota_is_terminal_but_a_rate_limit_is_retried():
    assert is_quota_exhausted(RateLimitError("insufficient_quota"))
    assert not nvidia_error_is_retryable(RateLimitError("insufficient_quota"))
    assert not is_quota_exhausted(RateLimitError("rate_limit_exceeded"))
    assert nvidia_error_is_retryable(RateLimitError("rate_limit_exceeded"))
    # Found through the cause chain, as the pipeline sees it.
    wrapped = LlmUnavailableError("classify failed")
    wrapped.__cause__ = RateLimitError("insufficient_quota")
    assert is_quota_exhausted(wrapped)


def test_openai_makes_one_request_on_exhausted_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    calls = []
    provider = OpenAIProvider(api_key="sk-test-not-real", model="gpt-4.1")
    provider.client = _client_raising(RateLimitError("insufficient_quota"), calls)
    with pytest.raises(ProviderQuotaExhausted):
        provider.classify_event("A lab released a model.")
    assert len(calls) == 1                                # no tenacity retry
    rows = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [(row["success"], row["error_type"]) for row in rows] == [(False, "RateLimitError")]


def test_openai_sdk_does_not_retry_behind_tenacity():
    provider = OpenAIProvider(api_key="sk-test-not-real", model="gpt-4.1")
    assert provider.client.max_retries == 0


def test_category_batch_stops_at_exhausted_quota(monkeypatch):
    import app.core.consolidate as consolidate

    sleeps, calls = [], []
    monkeypatch.setattr("time.sleep", lambda seconds: sleeps.append(seconds))

    class NoQuota(TestLLMProvider):
        def classify_categories(self, cards):
            calls.append(cards)
            raise ProviderQuotaExhausted("insufficient_quota")

    with pytest.raises(ProviderQuotaExhausted):
        consolidate._classify_batch(NoQuota(), [("c1", "Card")], pause_seconds=3)
    assert len(calls) == 1 and sleeps == []               # no 20 s wait, no second request


# ── Normal test runs cannot reach a paid provider ───────────────────────────

def test_normal_runs_have_no_provider_credentials():
    if os.environ.get("RUN_LIVE_LLM_TESTS") == "1":
        pytest.skip("live run requested")
    from app.core.config import settings

    names = ("OPENAI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY")
    # Only names are ever compared, so a failure can never print a key.
    assert [name for name in names if os.environ.get(name)] == []
    assert [name for name in names if getattr(settings, name, None)] == []
    # A real provider built in a normal run has no client and fails closed.
    assert OpenAIProvider().client is None
    with pytest.raises(LlmUnavailableError):
        OpenAIProvider().classify_event("text")


def test_live_marked_tests_are_skipped_without_explicit_opt_in(monkeypatch):
    import conftest
    import pytest as _pytest

    class Item:
        def __init__(self, marker):
            self.marker = marker
            self.added = []

        def get_closest_marker(self, name):
            return object() if name == self.marker else None

        def add_marker(self, mark):
            self.added.append(mark)

    live_nvidia, live_openai, normal = Item("live_nvidia"), Item("live_openai"), Item(None)
    monkeypatch.setattr(conftest, "LIVE_REQUESTED", False)
    conftest.pytest_collection_modifyitems(None, [live_nvidia, live_openai, normal])
    assert live_nvidia.added and live_openai.added and not normal.added
    assert live_nvidia.added[0].mark.name == _pytest.mark.skip.name

    opted_in = Item("live_openai")
    monkeypatch.setattr(conftest, "LIVE_REQUESTED", True)
    conftest.pytest_collection_modifyitems(None, [opted_in])
    assert not opted_in.added


# ── Dry runs never write, and never spend without an estimate ──────────────

@pytest.fixture
def cli(db_session, monkeypatch):
    """manage_sources against the test database, with any provider call failing the test."""
    import manage_sources
    import app.core.providers.llm as llm

    monkeypatch.setattr(manage_sources, "_ready", lambda: db_session)

    def forbidden(*args, **kwargs):
        raise AssertionError("no provider may be created in this command")

    monkeypatch.setattr(llm, "get_llm_provider", forbidden)
    return manage_sources


def _event(db_session, headline):
    from app.models.event import Event
    from app.models.source import Source

    source = db_session.query(Source).first()
    event = Event(id=uuid.uuid4(), headline=headline, short_summary=f"{headline}.", primary_source_id=source.id,
                  version=1, importance_score=60, importance_reasoning={"event_kind": "capability"})
    db_session.add(event)
    db_session.commit()
    return event


def test_backfill_default_is_an_estimate_with_no_request_and_no_write(cli, db_session, capsys):
    from app.models.event import Event

    event = _event(db_session, "Wardrobe assistant ships")
    assert cli.main(["backfill-categories"]) == 0
    out = capsys.readouterr().out
    assert "estimate: 1 events, 2 requests" in out and "No requests made" in out
    db_session.expire_all()
    assert "market_category" not in db_session.get(Event, event.id).importance_reasoning


def test_dry_runs_refuse_to_overwrite_a_saved_file(cli, db_session, tmp_path):
    saved = tmp_path / "reviewed.json"
    saved.write_text("[]", encoding="utf-8")
    _event(db_session, "Wardrobe assistant ships")
    assert cli.main(["backfill-categories", "--run", str(saved)]) == 2
    assert cli.main(["rebuild-digest-card", "--event", str(uuid.uuid4()), "--run", str(saved)]) == 2
    assert saved.read_text(encoding="utf-8") == "[]"


def test_rebuild_run_needs_an_event_and_apply_needs_a_proposal(cli, db_session, tmp_path):
    from app.models.event import Event

    assert cli.main(["rebuild-digest-card", "--run", str(tmp_path / "p.json")]) == 2
    event = _event(db_session, "22 Nations Call for Global AI Oversight Body")
    not_proposed = tmp_path / "not-proposed.json"
    not_proposed.write_text(json.dumps({"status": "no evidence found in the lead story",
                                        "event_id": str(event.id)}), encoding="utf-8")
    assert cli.main(["rebuild-digest-card", "--apply", str(not_proposed)]) == 0
    db_session.expire_all()
    assert db_session.get(Event, event.id).headline == "22 Nations Call for Global AI Oversight Body"
