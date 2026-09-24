"""
A re-fetched article whose page differs only in counters and relative times
is not a new version. Found live: every Hugging Face post was re-summarized
on every poll because its upvote count and "3 days ago" changed.
"""
from datetime import datetime, timezone

from app.core.deduplication import is_immaterial_change
from app.core.parser import ArticleData
from app.core.pipeline import IntelligencePipeline
from app.models.article import Article
from app.models.event import Event
from app.models.source import Source

BODY = (
    "Tokenizers v1 release candidate is 3x to 30x faster than v0.23 on common workloads. "
    "It keeps the same token IDs as v0.23 for every supported model family. "
)


def _page(upvotes, age, extra=""):
    return f"{BODY * 3} Upvote {upvotes} +{upvotes - 6} lain {age} ago nice work{extra}"


def test_counters_and_relative_times_are_immaterial():
    assert is_immaterial_change(_page(64, "1 day"), _page(72, "3 days"))
    assert is_immaterial_change('"followerCount": 4160, x', '"followerCount": 4172, x')
    assert is_immaterial_change("Related post 19 August 17 More", "Related post 20 August 17 More")
    assert is_immaterial_change("Arrow ＞ next", "Arrow > next")


def test_real_corrections_stay_material():
    assert not is_immaterial_change("Snorkel AI raised $300 million this week.", "Snorkel AI raised $350 million this week.")
    assert not is_immaterial_change("Latency fell 40% on GPT-6.", "Latency fell 60% on GPT-6.")
    assert not is_immaterial_change("The model ships on 19 August 2026.", "The model ships on 20 August 2026.")
    assert not is_immaterial_change("Training took 3 days.", "Training took 5 days.")
    assert not is_immaterial_change(BODY, BODY + " Update: the release is delayed until October.")
    assert not is_immaterial_change("", BODY)


def _process(db_session, content):
    source = db_session.query(Source).first()
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.process_article(
        ArticleData(
            title="Tokenizers v1 release candidate",
            url="https://huggingface.co/blog/tokenizers-v1",
            content=content,
            published_at=datetime.now(timezone.utc),
        ),
        source.id,
    )
    return pipeline.last_outcome


def test_refetch_with_only_counter_changes_creates_no_version(db_session):
    assert _process(db_session, _page(64, "1 day")) == "created"
    assert _process(db_session, _page(72, "3 days")) == "duplicate"
    assert _process(db_session, _page(80, "5 days")) == "duplicate"
    assert db_session.query(Article).count() == 1
    assert db_session.query(Event).count() == 1


def test_a_material_edit_still_creates_a_superseding_version(db_session):
    assert _process(db_session, _page(64, "1 day")) == "created"
    assert _process(db_session, _page(64, "1 day", " Update: v1 final is delayed to October.")) == "created"
    live = db_session.query(Event).filter(Event.superseded_by_id.is_(None)).all()
    assert len(live) == 1 and live[0].version == 2
    # Churn after the material edit compares with the latest version, not the original.
    assert _process(db_session, _page(90, "4 days", " Update: v1 final is delayed to October.")) == "duplicate"
    assert db_session.query(Event).count() == 2
