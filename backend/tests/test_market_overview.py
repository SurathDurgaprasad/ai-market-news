"""Overview counts come from canonical events, not article copies."""
from datetime import datetime, timezone

from app.core.market import MarketEvent, build_market_overview, market_category, source_availability


def _event(
    event_id,
    headline,
    importance,
    when,
    *,
    entities=None,
    kind="other",
    sources=None,
    tiers=None,
    org="",
    source_name="Example",
    summary="",
):
    return MarketEvent(
        id=event_id,
        headline=headline,
        summary=summary or headline,
        importance=importance,
        occurred_at=when,
        entities=entities or [],
        event_kind=kind,
        source_names=sources or [source_name],
        source_tiers=tiers or ["secondary"],
        organization_name=org,
        primary_source_name=source_name,
    )


NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)
TODAY = datetime(2026, 9, 23, 2, 0, tzinfo=timezone.utc)
YESTERDAY = datetime(2026, 9, 22, 18, 0, tzinfo=timezone.utc)
MONDAY = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def test_one_publisher_does_not_invent_a_trend_from_copies():
    overview = build_market_overview(
        [
            _event("a", "OpenAI releases a model", 80, TODAY, kind="model_release", source_name="OpenAI Blog", tiers=["primary"]),
            _event("b", "OpenAI releases another model", 80, YESTERDAY, kind="model_release", source_name="OpenAI Blog", tiers=["primary"]),
        ],
        now=NOW,
    )
    assert overview["pulse"][0]["label"] == "Models"
    assert overview["pulse"][0]["week"] == 2
    assert overview["trending"] == []


def test_two_publishers_can_trend_a_real_category():
    overview = build_market_overview(
        [
            _event("a", "Lab publishes an agent benchmark", 70, TODAY, kind="research", entities=["OpenAI"], source_name="OpenAI Blog", tiers=["primary"], summary="A new agent benchmark."),
            _event("b", "Vendor ships a support agent for operations", 70, YESTERDAY, kind="capability", source_name="MIT Technology Review", tiers=["secondary"], summary="A separate support agent for operations."),
        ],
        now=NOW,
    )
    labels = [item["label"] for item in overview["trending"]]
    assert "Agents" in labels
    agents = next(item for item in overview["trending"] if item["label"] == "Agents")
    assert agents["week"] == 2
    assert agents["sources"] == 2
    assert agents["recent"] == 2
    assert "activity" not in agents


def test_week_old_importance_is_not_happening_now():
    overview = build_market_overview(
        [
            _event("old", "Monday research result", 95, MONDAY, kind="research", source_name="Microsoft Research", tiers=["primary"]),
            _event("now", "OpenAI introduces a model", 80, TODAY, kind="model_release", entities=["OpenAI"], source_name="OpenAI Blog", tiers=["primary"]),
        ],
        now=NOW,
    )
    now_ids = [item["id"] for item in overview["happening_now"]]
    biggest_ids = [item["id"] for item in overview["biggest"]]
    assert "now" in now_ids
    assert "old" not in now_ids
    assert "old" in biggest_ids
    assert set(now_ids).isdisjoint(biggest_ids)


def test_player_counts_follow_stored_events():
    overview = build_market_overview(
        [
            _event("a", "Introduction of a model", 80, TODAY, entities=["OpenAI"], kind="model_release", source_name="OpenAI Blog", tiers=["primary"]),
            _event("b", "OpenAI posts an earlier note", 60, YESTERDAY, entities=["OpenAI"], kind="capability", source_name="The Verge", tiers=["secondary"]),
            _event("c", "Unrelated hardware", 70, TODAY, entities=["NVIDIA"], kind="hardware_platform", source_name="NVIDIA AI Blog", tiers=["primary"]),
        ],
        now=NOW,
    )
    openai = next(item for item in overview["players"] if item["slug"] == "openai")
    nvidia = next(item for item in overview["players"] if item["slug"] == "nvidia")
    assert openai["week"] == 2
    assert openai["significant"] == 1
    assert openai["sources"] == 2
    assert openai["latest_event_id"] == "a"
    assert nvidia["week"] == 1
    assert nvidia["significant"] == 1
    assert all(item["week"] > 0 for item in overview["players"])


def test_biggest_does_not_repeat_one_organization():
    overview = build_market_overview(
        [
            _event("now", "OpenAI introduces a model", 80, TODAY, entities=["OpenAI"], kind="model_release", source_name="OpenAI Blog", org="OpenAI", tiers=["primary"]),
            _event("a1", "Amazon ships one platform", 90, MONDAY, entities=["Amazon"], kind="hardware_platform", source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
            _event("a2", "Amazon ships another platform", 88, MONDAY, entities=["Amazon"], kind="hardware_platform", source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
            _event("m", "Microsoft publishes a result", 85, MONDAY, entities=["Microsoft"], kind="research", source_name="Microsoft Research", org="Microsoft", tiers=["research"]),
        ],
        now=NOW,
    )
    orgs = [item["organization"] for item in overview["biggest"]]
    assert orgs.count("Amazon") == 1
    assert "Microsoft" in orgs


def test_a_multi_company_roundup_is_not_each_players_development():
    overview = build_market_overview(
        [
            _event(
                "roundup",
                "Survey of labs",
                60,
                TODAY,
                entities=["OpenAI", "Anthropic", "Meta", "Google"],
                source_name="Hacker News",
                org="Hacker News",
            ),
            _event(
                "real",
                "OpenAI introduces a model",
                80,
                YESTERDAY,
                entities=["OpenAI"],
                kind="model_release",
                source_name="OpenAI Blog",
                org="OpenAI",
                tiers=["primary"],
            ),
        ],
        now=NOW,
    )
    openai = next(item for item in overview["players"] if item["slug"] == "openai")
    assert openai["week"] == 1
    assert openai["latest_event_id"] == "real"
    assert all(item["slug"] != "anthropic" for item in overview["players"])
    shown = [item["id"] for item in overview["happening_now"] + overview["biggest"]]
    assert "roundup" not in shown


def test_a_name_in_the_entity_list_alone_is_not_that_players_development():
    overview = build_market_overview(
        [
            _event(
                "mention",
                "TypeSafe introduces a model",
                60,
                TODAY,
                entities=["TypeSafe", "OpenAI"],
                source_name="Hacker News",
                org="Hacker News",
            ),
        ],
        now=NOW,
    )
    assert overview["players"] == []


def test_a_lone_roundup_is_labeled_with_its_publisher():
    overview = build_market_overview(
        [
            _event(
                "roundup",
                "Survey of labs",
                60,
                TODAY,
                entities=["OpenAI", "Anthropic", "Meta", "Google"],
                source_name="Hacker News",
                org="Hacker News",
                tiers=["community"],
            ),
        ],
        now=NOW,
    )
    assert overview["happening_now"][0]["organization"] == "Hacker News"


def test_discussion_does_not_lead_when_direct_developments_exist():
    overview = build_market_overview(
        [
            _event("talk", "GPT-6 breaks a puzzle", 95, TODAY, kind="capability", source_name="Hacker News", tiers=["community"]),
            _event("model", "OpenAI introduces a model", 80, TODAY, kind="model_release", source_name="OpenAI Blog", org="OpenAI", tiers=["primary"]),
            _event("paper", "Microsoft publishes a result", 75, YESTERDAY, kind="research", source_name="Microsoft Research", org="Microsoft", tiers=["research"]),
            _event("chip", "NVIDIA announces a platform", 75, YESTERDAY, kind="hardware_platform", source_name="NVIDIA AI Blog", org="NVIDIA", tiers=["primary"]),
        ],
        now=NOW,
    )
    ids = [item["id"] for item in overview["happening_now"]]
    assert "talk" not in ids
    assert ids[0] == "model"


def test_roundup_does_not_outrank_a_research_publication():
    overview = build_market_overview(
        [
            _event("now", "OpenAI introduces a model", 80, TODAY, kind="model_release", entities=["OpenAI"], source_name="OpenAI Blog", org="OpenAI", tiers=["primary"]),
            _event(
                "hn",
                "Chinese AI companies lead in open-weight models",
                90,
                YESTERDAY,
                entities=["OpenAI", "Anthropic", "Meta", "Google"],
                source_name="Hacker News",
                tiers=["community"],
            ),
            _event("paper", "Microsoft publishes a result", 80, MONDAY, kind="research", entities=["Microsoft"], source_name="Microsoft Research", org="Microsoft", tiers=["research"]),
        ],
        now=NOW,
    )
    big_ids = [item["id"] for item in overview["biggest"]]
    assert "hn" not in big_ids
    assert "paper" in big_ids


def test_a_named_model_is_categorized_when_the_kind_is_generic():
    event = _event("a", "TypeSafe introduces a large language model", 70, TODAY, kind="capability")
    assert market_category(event) == "Models"


def test_recent_cluster_is_reported_as_a_count():
    third = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)
    overview = build_market_overview(
        [
            _event("a", "First agent benchmark", 70, TODAY, kind="research", summary="An agent benchmark.", source_name="OpenAI Blog", tiers=["primary"]),
            _event("b", "Second agent note", 60, YESTERDAY, kind="research", summary="Another agent result.", source_name="MIT Technology Review", tiers=["secondary"]),
            _event("c", "Third agent result", 70, third, kind="capability", summary="A further agent result.", source_name="The Verge", tiers=["secondary"]),
        ],
        now=NOW,
    )
    agents = next(item for item in overview["trending"] if item["label"] == "Agents")
    assert agents["recent"] == 3
    assert agents["sources"] == 3
    assert "activity" not in agents


def test_a_model_release_outranks_a_personnel_note():
    overview = build_market_overview(
        [
            _event("hire", "Jun Kim joins Hugging Face", 80, TODAY, kind="partnership", source_name="Hugging Face Blog", org="Hugging Face", tiers=["primary"]),
            _event("model", "Anthropic introduces a model", 75, YESTERDAY, kind="model_release", entities=["Anthropic"], source_name="The Verge", tiers=["secondary"]),
        ],
        now=NOW,
    )
    ids = [item["id"] for item in overview["happening_now"]]
    assert ids[0] == "model"


def test_a_customer_deployment_is_not_a_significant_development():
    overview = build_market_overview(
        [
            _event("deploy", "Trane Technologies Implements an AI platform", 80, TODAY, entities=["Amazon"], source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
            _event("model", "Amazon announces a model on Bedrock", 80, YESTERDAY, entities=["Amazon"], kind="model_release", source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
        ],
        now=NOW,
    )
    amazon = next(item for item in overview["players"] if item["slug"] == "amazon")
    assert amazon["week"] == 2
    assert amazon["significant"] == 1


def test_a_summary_mention_does_not_recategorize_a_model_release():
    event = _event(
        "a",
        "Lab launches a system on a cloud platform",
        80,
        TODAY,
        kind="model_release",
        summary="The writeup mentions an agent workflow in passing.",
    )
    assert market_category(event) == "Models"


def test_research_kind_does_not_invent_a_research_source():
    event = _event(
        "a",
        "A laboratory publishes a result",
        70,
        TODAY,
        kind="research",
        tiers=["secondary"],
        source_name="Example Review",
    )
    assert source_availability(event) == "Supporting coverage"


def test_repeated_coverage_occupies_one_now_slot():
    overview = build_market_overview(
        [
            _event(
                "intro",
                "Introduction of Northwind 4.2 for general reasoning",
                80,
                TODAY,
                kind="model_release",
                source_name="Northwind Blog",
                org="OpenAI",
                tiers=["primary"],
            ),
            _event(
                "dist",
                "Northwind 4.2 for general reasoning now available on a cloud",
                90,
                TODAY,
                kind="model_release",
                source_name="Cloud Blog",
                org="Amazon",
                tiers=["primary"],
            ),
            _event(
                "chip",
                "Vendor unveils a local inference processor",
                75,
                YESTERDAY,
                kind="hardware_platform",
                source_name="Vendor News",
                entities=["NVIDIA"],
                tiers=["secondary"],
            ),
        ],
        now=NOW,
    )
    now_ids = [item["id"] for item in overview["happening_now"]]
    assert not ({"intro", "dist"} <= set(now_ids))
    assert "intro" in now_ids or "dist" in now_ids
    assert "chip" in now_ids


def test_overlapping_coverage_counts_as_one_development():
    overview = build_market_overview(
        [
            _event(
                "a",
                "Investigation reveals failures in regional border surveillance",
                75,
                MONDAY,
                kind="research",
                tiers=["secondary"],
                source_name="Review Desk",
            ),
            _event(
                "b",
                "Regional border surveillance fails during the investigation",
                70,
                MONDAY,
                kind="research",
                tiers=["research"],
                source_name="Field Journal",
            ),
        ],
        now=NOW,
    )
    research = next(item for item in overview["pulse"] if item["label"] == "Research")
    assert research["week"] == 1


def test_category_is_keyword_before_a_generic_kind():
    event = _event(
        "a",
        "New coding agent lands",
        70,
        TODAY,
        kind="capability",
        summary="The coding agent writes software.",
    )
    assert market_category(event) == "Coding"


def test_pulse_examples_do_not_repeat_one_development():
    overview = build_market_overview(
        [
            _event("intro", "Introduction of Northwind 4.2 for general reasoning", 80, TODAY, kind="model_release", org="OpenAI", source_name="Northwind Blog", tiers=["primary"]),
            _event("dist", "Northwind 4.2 for general reasoning now available on a cloud", 85, TODAY, kind="model_release", org="Amazon", source_name="Cloud Blog", tiers=["primary"]),
            _event("other", "Harbor introduces a separate reasoning model", 75, YESTERDAY, kind="model_release", org="Anthropic", entities=["Anthropic"], source_name="The Verge", tiers=["secondary"]),
        ],
        now=NOW,
    )
    models = next(item for item in overview["pulse"] if item["label"] == "Models")
    headlines = [example["headline"] for example in models["examples"]]
    assert sum("Northwind 4.2" in headline for headline in headlines) == 1
    assert "Harbor introduces a separate reasoning model" in headlines


def test_published_volume_is_not_substantive_activity():
    overview = build_market_overview(
        [
            _event("model", "Amazon announces a foundation model", 80, TODAY, kind="model_release", entities=["Amazon"], source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
            _event("hire", "A researcher joins the Amazon lab", 80, YESTERDAY, kind="partnership", entities=["Amazon"], source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
            _event("deploy", "A retailer implements an Amazon platform", 80, YESTERDAY, entities=["Amazon"], source_name="AWS Machine Learning Blog", org="Amazon", tiers=["primary"]),
        ],
        now=NOW,
    )
    amazon = next(item for item in overview["players"] if item["slug"] == "amazon")
    assert amazon["week"] == 3
    assert amazon["substantive"] == 1


def test_a_second_major_release_is_not_crowded_out():
    fillers = [
        _event("sec", "Lab discloses a malware campaign", 55, TODAY, kind="security_incident", source_name="Security Desk"),
        _event("hw", "Vendor unveils a local inference processor", 55, TODAY, kind="hardware_platform", source_name="Hardware Desk"),
        _event("oss", "Project publishes an open source runtime", 55, TODAY, kind="open_source_release", source_name="Code Desk"),
        _event("fund", "Startup closes a funding round", 55, TODAY, kind="funding", source_name="Deal Desk"),
        _event("bench", "Lab publishes a benchmark suite", 55, TODAY, kind="benchmark", source_name="Eval Desk"),
    ]
    overview = build_market_overview(
        fillers
        + [
            _event("first", "Northwind introduces a reasoning model", 80, TODAY, kind="model_release", org="OpenAI", source_name="OpenAI Blog", tiers=["primary"]),
            _event("second", "Harbor introduces a separate reasoning model", 85, YESTERDAY, kind="model_release", org="Anthropic", entities=["Anthropic"], source_name="The Verge", tiers=["secondary"]),
        ],
        now=NOW,
    )
    now_ids = [item["id"] for item in overview["happening_now"]]
    assert "first" in now_ids
    assert "second" in now_ids
    assert len(now_ids) <= 6


def test_concentrated_recent_activity_ranks_ahead_of_a_larger_older_set():
    recent_agents = [
        _event("a1", "Vendor ships a support agent for operations", 70, TODAY, kind="capability", source_name="First Desk"),
        _event("a2", "Laboratory deploys a maintenance agent", 70, YESTERDAY, kind="capability", source_name="Second Desk"),
    ]
    older_models = [
        _event("m1", "Atlas releases a vision model", 70, MONDAY, kind="model_release", source_name="Atlas Blog", tiers=["primary"]),
        _event("m2", "Beacon releases a speech model", 70, MONDAY, kind="model_release", source_name="Beacon Blog", tiers=["primary"]),
        _event("m3", "Cedar releases a retrieval model", 70, MONDAY, kind="model_release", source_name="Cedar Blog", tiers=["primary"]),
        _event("m4", "Delta releases a compact model", 70, TODAY, kind="model_release", source_name="Delta Blog", tiers=["primary"]),
    ]
    overview = build_market_overview(recent_agents + older_models, now=NOW)
    assert overview["trending"][0]["label"] == "Agents"
    assert "emerging" not in overview["trending"][0]
    agents = next(item for item in overview["pulse"] if item["label"] == "Agents")
    assert [example["headline"] for example in agents["examples"]] == [
        "Vendor ships a support agent for operations",
        "Laboratory deploys a maintenance agent",
    ]
