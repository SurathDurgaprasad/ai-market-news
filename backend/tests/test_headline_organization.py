"""A generated headline keeps its organization only when it is confidently known."""
from app.core.headlines import leading_actor, restore_headline_organization

SNORKEL_BODY = (
    "Snorkel AI has raised $350 million in a Series E round. "
    "Snorkel AI said demand for AI training data tripled this year."
)


def _restore(headline, title, body, entities=(), publishers=("TechCrunch AI", "TechCrunch")):
    return restore_headline_organization(
        headline, source_title=title, content=body, entities=entities, publisher_names=publishers
    )


def test_funding_headline_with_a_placeholder_gets_the_organization():
    assert _restore(
        "Startup Raises $350 Million Series E Funding",
        "Snorkel AI triples valuation to $3.5B as demand for AI training data booms",
        SNORKEL_BODY,
    ) == "Snorkel AI Raises $350 Million Series E Funding"


def test_organization_already_present_is_unchanged():
    headline = "OpenAI Releases GPT-6 Sol and Luna Models"
    assert _restore(headline, "OpenAI releases GPT-6", "OpenAI released GPT-6 today.") == headline


def test_headline_without_a_placeholder_is_never_prefixed():
    """Organization absent but no placeholder: no 'OpenAI: ...' or guessed prefixes."""
    for headline in (
        "Introduction of GPT-6 Sol and Luna Models",
        "Release of PP-OCRv6 with Enhanced OCR Capabilities",
        "Developer Tools Get an Upgrade in Visual Studio",
    ):
        assert _restore(headline, "PaddleOCR ships PP-OCRv6", "PaddleOCR ships PP-OCRv6 today.") == headline


def test_multiple_organizations_are_ambiguous_and_unchanged():
    headline = "Startup Partners on Data Center Build-Out"
    title = "OpenAI and Microsoft expand data center partnership"
    body = "OpenAI and Microsoft announced an expanded data center partnership."
    assert _restore(headline, title, body) == headline


def test_unknown_organization_is_unchanged():
    headline = "Startup Raises $50 Million for Robot Arms"
    assert _restore(headline, "Why robot arms are suddenly hot", "A startup raised $50 million.") == headline
    # The title leads with the investor, not the company that raised.
    assert _restore(headline, "Sequoia leads $50M round in Armada", "Armada raised $50 million.") == headline
    # An adjective lead does not name the actor.
    assert _restore(headline, "Nvidia-backed startup raises $50M", "A startup raised $50 million.") == headline
    # Same name, different kind of action than the headline.
    assert _restore(headline, "Armada launches a robot arm", "Armada launched a robot arm.") == headline


def test_the_title_is_the_publishers_own_attribution_even_when_the_body_is_a_teaser():
    """The real case: the stored body is only the RSS teaser and never names the company."""
    assert _restore(
        "Startup Raises $350 Million Series E Funding",
        "Snorkel AI triples valuation to $3.5B as demand for AI training data booms",
        "The seven-year-old startup has raised a $350 million Series E to fuel its data-as-a-service approach.",
    ) == "Snorkel AI Raises $350 Million Series E Funding"


def test_research_headline_keeps_the_people_noun_and_verb_agreement():
    assert _restore(
        "Researchers Develop a Language Model for Ancient Papyrus",
        "MIT CSAIL builds a language model to read ancient papyrus",
        "Researchers at MIT CSAIL built a model for papyrus fragments.",
    ) == "MIT CSAIL Researchers Develop a Language Model for Ancient Papyrus"


def test_product_release_headline_with_a_placeholder():
    assert _restore(
        "AI Startup Launches Coding Agent for Enterprises",
        "Cursor launches an enterprise coding agent",
        "Cursor today launched a coding agent for enterprise teams.",
        entities=["Cursor", "Cursor Agent"],
    ) == "Cursor Launches Coding Agent for Enterprises"


def test_publisher_is_never_used_as_the_organization():
    headline = "Startup Raises $20 Million"
    assert _restore(headline, "TechCrunch Disrupt: startup raises $20M", "TechCrunch reports a raise.") == headline


def test_proper_nouns_and_quoted_names_are_preserved():
    headline = 'Startup Unveils "Muse" Assistant With GPT-6 Astra'
    restored = _restore(headline, "Harbor unveils its Muse assistant", "Harbor unveiled the Muse assistant.")
    assert restored == 'Harbor Unveils "Muse" Assistant With GPT-6 Astra'


def test_leading_actor_rules():
    assert leading_actor("Snorkel AI triples valuation to $3.5B") == "Snorkel AI"
    assert leading_actor("Mistral's new model tops benchmarks") == "Mistral"
    assert leading_actor("How startups raise money") is None
    assert leading_actor("OpenAI and Microsoft expand ties") is None
    assert leading_actor("the quiet rise of small models") is None


def test_pipeline_restores_the_organization_on_a_new_event(db_session):
    """End to end: the summarizer's placeholder subject never reaches the stored event."""
    from app.core.ai_processor import SourceGroundedSummary
    from app.core.parser import ArticleData
    from app.core.pipeline import IntelligencePipeline
    from app.core.providers.llm import TestLLMProvider

    class PlaceholderSummary(TestLLMProvider):
        def summarize_event(self, content):
            return SourceGroundedSummary(
                headline="Startup Raises $350 Million Series E Funding",
                short_summary="A startup raised $350 million in Series E funding.",
                what_changed="- Raised $350 million",
                citations=["Snorkel AI has raised $350 million in a Series E round."],
            )

    source = db_session.query(__import__("app.models.source", fromlist=["Source"]).Source).first()
    pipeline = IntelligencePipeline(db_session, llm_env="test")
    pipeline.llm = PlaceholderSummary()
    event = pipeline.process_article(
        ArticleData(
            title="Snorkel AI triples valuation to $3.5B as demand for AI training data booms",
            url="https://news.example.com/snorkel",
            content=SNORKEL_BODY * 3,
        ),
        source.id,
    )
    assert event is not None
    assert event.headline == "Snorkel AI Raises $350 Million Series E Funding"
    assert event.citations == ["Snorkel AI has raised $350 million in a Series E round."]


def test_repair_stored_headlines_is_reversible_and_idempotent(db_session):
    import uuid

    from app.core.headlines import repair_stored_headlines
    from app.models.article import Article
    from app.models.event import Event, EventArticle
    from app.models.source import Source

    source = db_session.query(Source).first()
    article = Article(
        id=uuid.uuid4(), source_id=source.id, url="https://news.example.com/snorkel",
        title="Snorkel AI triples valuation to $3.5B", raw_content=SNORKEL_BODY, hash="h1",
    )
    event = Event(
        id=uuid.uuid4(), headline="Startup Raises $350 Million Series E Funding",
        short_summary="A startup raised $350 million.", primary_source_id=source.id,
        importance_reasoning={"event_kind": "funding"}, version=1,
    )
    db_session.add_all([article, event])
    db_session.flush()
    db_session.add(EventArticle(event_id=event.id, article_id=article.id, link_type="primary"))
    db_session.commit()

    assert repair_stored_headlines(db_session) == [
        ("Startup Raises $350 Million Series E Funding", "Snorkel AI Raises $350 Million Series E Funding")
    ]
    assert db_session.get(Event, event.id).headline.startswith("Startup")  # dry run changes nothing
    repair_stored_headlines(db_session, apply=True)
    stored = db_session.get(Event, event.id)
    assert stored.headline == "Snorkel AI Raises $350 Million Series E Funding"
    assert stored.importance_reasoning["original_headline"] == "Startup Raises $350 Million Series E Funding"
    assert stored.importance_reasoning["event_kind"] == "funding"
    assert repair_stored_headlines(db_session, apply=True) == []


def test_a_biotech_placeholder_gets_its_name_back():
    """Live: "AI Biotech Valued at $2 Billion" for TechCrunch's "Enveda secures $311M ..."."""
    from app.core.headlines import restore_headline_organization

    assert restore_headline_organization(
        "AI Biotech Valued at $2 Billion in Funding Round",
        source_title="Enveda secures $311M to bring more nature-derived AI drugs into clinical trials",
        content="The funding round valued the AI biotech at $2 billion.",
    ) == "Enveda Valued at $2 Billion in Funding Round"
    # A biotech named as the object, not the subject, is left alone.
    assert restore_headline_organization(
        "Investors Back AI Biotech Wave",
        source_title="Enveda secures $311M",
        content="",
    ) == "Investors Back AI Biotech Wave"
