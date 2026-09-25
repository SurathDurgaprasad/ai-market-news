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


def _version(db_session, source, content, url, version, created_at, headline):
    import uuid

    from app.models.event import EventArticle

    article = Article(id=uuid.uuid4(), source_id=source.id, url=url, title=headline,
                      raw_content=content, hash=str(uuid.uuid4()))
    event = Event(id=uuid.uuid4(), headline=headline, short_summary="s", primary_source_id=source.id,
                  version=version, created_at=created_at, importance_reasoning={"event_kind": "research"})
    db_session.add_all([article, event])
    db_session.flush()
    db_session.add(EventArticle(event_id=event.id, article_id=article.id, link_type="primary"))
    db_session.commit()
    return event


def test_repair_restores_first_recorded_time_only_for_churn_versions(db_session):
    from datetime import timedelta

    from app.core.consolidate import repair_churn_versions

    source = db_session.query(Source).first()
    first = datetime(2026, 9, 20, 8, 0)
    later = first + timedelta(days=4)
    # Churn: only counters changed.
    v1 = _version(db_session, source, _page(64, "1 day"), "https://hf.example/a", 1, first, "A v1")
    v2 = _version(db_session, source, _page(72, "3 days"), "https://hf.example/a#update-1", 2, later, "A v2")
    v1.superseded_by_id = v2.id
    # Material: an update paragraph was added.
    m1 = _version(db_session, source, BODY * 3, "https://hf.example/b", 1, first, "B v1")
    m2 = _version(db_session, source, BODY * 3 + " Update: delayed to October.", "https://hf.example/b#update-1", 2, later, "B v2")
    m1.superseded_by_id = m2.id
    db_session.commit()

    assert repair_churn_versions(db_session) == [("A v2", 2)]
    repair_churn_versions(db_session, apply=True)
    db_session.expire_all()
    repaired = db_session.get(Event, v2.id)
    assert repaired.created_at.replace(tzinfo=None) == first
    assert repaired.importance_reasoning["churn_created_at"].startswith("2026-09-24")
    assert repaired.importance_reasoning["event_kind"] == "research"
    assert db_session.get(Event, m2.id).created_at.replace(tzinfo=None) == later
    assert repair_churn_versions(db_session) == []


def test_old_known_articles_are_not_refetched(db_session):
    """A settled URL is a duplicate before any page download."""
    from datetime import timedelta

    source = db_session.query(Source).first()
    old = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.add(Article(source_id=source.id, url="https://blog.example.com/old-post", title="Old post",
                           raw_content=BODY, hash="h-old", published_at=old, ingested_at=old))
    db_session.commit()
    fetched = []

    def fetch(url, timeout=8):
        fetched.append(url)
        raise AssertionError("settled article must not be fetched")

    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.process_article(
        ArticleData(title="Old post", url="https://blog.example.com/old-post", content="", published_at=old),
        source.id,
        fetch_fn=fetch,
    )
    assert pipeline.last_outcome == "duplicate"
    assert fetched == []


def test_recent_known_articles_are_still_checked_for_edits(db_session):
    assert _process(db_session, _page(64, "1 day")) == "created"
    assert _process(db_session, _page(64, "1 day", " Update: v1 final is delayed to October.")) == "created"


def test_repair_with_refetch_catches_chrome_rotation_but_not_real_edits(db_session):
    """Stored versions differ only by a rotating promo; today's extractor drops it."""
    from datetime import timedelta

    from app.core.consolidate import repair_churn_versions

    source = db_session.query(Source).first()
    first = datetime(2026, 9, 20, 8, 0)
    later = first + timedelta(days=4)
    promo_a = " PODCAST SERIES The AI Revolution in Medicine. Listen now."
    promo_b = " Microsoft Research at BUILD 2026. Giving developers a hands-on look. Learn more."
    p1 = _version(db_session, source, BODY * 3 + promo_a, "https://ms.example/p", 1, first, "P v1")
    p2 = _version(db_session, source, BODY * 3 + promo_b, "https://ms.example/p#update-1", 2, later, "P v2")
    p1.superseded_by_id = p2.id
    p2.article_url = "https://ms.example/p#update-1"
    e1 = _version(db_session, source, BODY * 3 + promo_a, "https://ms.example/e", 1, first, "E v1")
    e2 = _version(db_session, source, BODY * 3 + " Update: CARE-X v2 adds CT support." + promo_b,
                  "https://ms.example/e#update-1", 2, later, "E v2")
    e1.superseded_by_id = e2.id
    e2.article_url = "https://ms.example/e#update-1"
    db_session.commit()

    live_pages = {
        "https://ms.example/p": BODY * 3,
        "https://ms.example/e": BODY * 3 + " Update: CARE-X v2 adds CT support.",
    }
    fetched = []

    def refetch(url):
        fetched.append(url)
        return live_pages.get(url)

    # Without refetch the stored promo swap looks material.
    assert repair_churn_versions(db_session) == []
    assert repair_churn_versions(db_session, refetch=refetch) == [("P v2", 2)]
    assert set(fetched) == {"https://ms.example/p", "https://ms.example/e"}


def _article_at(db_session, url, content, title="Tokenizers v1 release candidate"):
    source = db_session.query(Source).first()
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    event = pipeline.process_article(
        ArticleData(title=title, url=url, content=content, published_at=datetime.now(timezone.utc)),
        source.id,
    )
    return pipeline, event


def _links(db_session, event):
    from app.models.event import EventArticle

    rows = (
        db_session.query(EventArticle.link_type, Article.url)
        .join(Article, EventArticle.article_id == Article.id)
        .filter(EventArticle.event_id == event.id)
        .all()
    )
    return sorted((link_type, url) for link_type, url in rows)


def test_an_edited_supporting_report_is_evidence_not_a_new_version(db_session):
    """Live: an edit to a merged report replaced the card and stranded its evidence."""
    from app.models.event import EventArticle

    _pipeline, card = _article_at(db_session, "https://lab.example/official", BODY * 3)
    source = db_session.query(Source).first()
    report = Article(source_id=source.id, url="https://news.example/report", title="Report",
                     raw_content=BODY * 2 + " Reporters add context.", hash="h-report")
    db_session.add(report)
    db_session.flush()
    db_session.add(EventArticle(event_id=card.id, article_id=report.id, link_type="supporting"))
    db_session.commit()

    pipeline, event = _article_at(
        db_session, "https://news.example/report",
        BODY * 2 + " Reporters add context. Update: the vendor confirmed the date.", title="Report",
    )
    assert pipeline.last_outcome == "linked"
    assert event.id == card.id
    live = db_session.query(Event).filter(Event.superseded_by_id.is_(None)).all()
    assert [e.id for e in live] == [card.id] and live[0].version == 1
    assert [link for link, _url in _links(db_session, card)].count("supporting") == 2


def test_a_new_version_keeps_the_cards_other_evidence(db_session):
    from app.models.event import EventArticle

    _pipeline, card = _article_at(db_session, "https://lab.example/official", BODY * 3)
    source = db_session.query(Source).first()
    report = Article(source_id=source.id, url="https://news.example/report", title="Report",
                     raw_content="Coverage of the release.", hash="h-report-2")
    db_session.add(report)
    db_session.flush()
    db_session.add(EventArticle(event_id=card.id, article_id=report.id, link_type="supporting"))
    db_session.commit()

    pipeline, new_version = _article_at(
        db_session, "https://lab.example/official", BODY * 3 + " Update: the release is delayed until October."
    )
    assert pipeline.last_outcome == "created" and new_version.version == 2
    links = _links(db_session, new_version)
    assert ("supporting", "https://news.example/report") in links
    assert [link for link, _url in links].count("primary") == 1
    # The edited page's previous text stays with the superseded version only.
    assert all(url != "https://lab.example/official" for _link, url in links)


def test_repair_restores_evidence_left_on_old_versions(db_session):
    import uuid

    from app.core.consolidate import restore_version_evidence
    from app.models.event import EventArticle

    source = db_session.query(Source).first()
    first = datetime(2026, 9, 20, 8, 0)
    v1 = _version(db_session, source, BODY, "https://lab.example/p", 1, first, "P v1")
    v1.article_url = "https://lab.example/p"
    report = Article(id=uuid.uuid4(), source_id=source.id, url="https://news.example/r", title="R",
                     raw_content="Coverage.", hash="h-r")
    db_session.add(report)
    db_session.flush()
    db_session.add(EventArticle(event_id=v1.id, article_id=report.id, link_type="supporting"))
    v2 = _version(db_session, source, BODY + " Update.", "https://lab.example/p#update-1", 2, first, "P v2")
    v2.article_url = "https://lab.example/p"
    v1.superseded_by_id = v2.id
    db_session.commit()

    assert restore_version_evidence(db_session) == [("P v2", 1)]
    restore_version_evidence(db_session, apply=True)
    urls = {a.url for a in db_session.query(Article).join(EventArticle, EventArticle.article_id == Article.id)
            .filter(EventArticle.event_id == v2.id)}
    assert urls == {"https://lab.example/p#update-1", "https://news.example/r"}
    assert restore_version_evidence(db_session) == []


def test_restored_evidence_must_be_the_same_development(db_session):
    """Some old merges attached related work; the relationship model gates what comes back."""
    import uuid

    from app.core.consolidate import restore_version_evidence
    from app.core.providers.llm import TestLLMProvider
    from app.models.event import EventArticle

    source = db_session.query(Source).first()
    first = datetime(2026, 9, 20, 8, 0)
    v1 = _version(db_session, source, BODY, "https://lab.example/q", 1, first, "Q v1")
    for url, text in (("https://news.example/same", "duplicate_trigger same launch"),
                      ("https://news.example/tutorial", "related_trigger a tutorial")):
        article = Article(id=uuid.uuid4(), source_id=source.id, url=url, title=url, raw_content=text,
                          hash=str(uuid.uuid4()))
        db_session.add(article)
        db_session.flush()
        db_session.add(EventArticle(event_id=v1.id, article_id=article.id, link_type="supporting"))
    v2 = _version(db_session, source, BODY + " Update.", "https://lab.example/q#update-1", 2, first, "Q v2")
    v2.article_url = "https://lab.example/q"
    v1.superseded_by_id = v2.id
    db_session.commit()

    assert restore_version_evidence(db_session, llm=TestLLMProvider(), apply=True) == [("Q v2", 1)]
    urls = {a.url for a in db_session.query(Article).join(EventArticle, EventArticle.article_id == Article.id)
            .filter(EventArticle.event_id == v2.id)}
    assert "https://news.example/same" in urls
    assert "https://news.example/tutorial" not in urls
