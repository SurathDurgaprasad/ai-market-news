"""Headline relationships stay specific. Marker and contrast guards still apply."""
from app.core.deduplication import classify_headline_relationship
from app.core.providers.llm import EventRelationship


def _rel(left, right, kind1="", kind2=""):
    return classify_headline_relationship(left, right, kind1, kind2)


def test_punctuation_variation_is_the_same_event():
    assert _rel(
        "Deaths near the U.S.-Mexico border surveillance towers",
        "Deaths near the US-Mexico border surveillance towers",
    ) == EventRelationship.SAME_EVENT


def test_wording_variation_of_one_investigation_is_the_same_event():
    assert _rel(
        "Investigation Reveals Deaths Near US-Mexico Border Surveillance Towers",
        "Investigation Reveals Failures in US-Mexico Border Surveillance Technology",
    ) == EventRelationship.SAME_EVENT


def test_different_article_angles_of_one_finding_are_the_same_event():
    assert _rel(
        "New surveillance towers fail to prevent migrant deaths",
        "Surveillance technology fails to prevent migrant deaths at the U.S.-Mexico border",
    ) == EventRelationship.SAME_EVENT


def test_same_product_with_a_different_event_stays_different():
    assert _rel(
        "Harbor introduces a reasoning model",
        "Harbor raises a funding round for its lab",
    ) == EventRelationship.DIFFERENT_EVENT


def test_release_and_distribution_are_an_update_not_a_new_event():
    assert _rel(
        "Introduction of Northwind 4.2 for general reasoning",
        "Northwind 4.2 for general reasoning now available on a cloud",
    ) == EventRelationship.UPDATE_TO_SAME_EVENT


def test_later_confirmation_of_an_incident_is_the_same_event():
    assert _rel(
        "Vendor discloses a token theft incident",
        "Vendor confirms the token theft incident",
    ) == EventRelationship.SAME_EVENT


def test_research_and_a_product_release_stay_different():
    assert _rel(
        "Lab publishes a paper about harbor retrieval",
        "Lab releases the harbor retrieval model",
        "research",
        "model_release",
    ) == EventRelationship.DIFFERENT_EVENT


def test_a_separate_investigation_stays_different():
    assert _rel(
        "Inquiry finds failures in coastal radar tracking",
        "Inquiry finds failures in airport baggage screening",
    ) == EventRelationship.DIFFERENT_EVENT


def test_a_swapped_subject_on_one_template_stays_different():
    assert _rel(
        "Baseten becomes supported inference provider on Hugging Face",
        "DeepInfra becomes supported inference provider on Hugging Face",
    ) == EventRelationship.DIFFERENT_EVENT


def test_same_model_used_for_different_work_stays_different():
    assert _rel(
        "GPT-6 Astra enhances data visualization for Hex",
        "GPT-6 Astra enhances software testing capabilities",
    ) == EventRelationship.DIFFERENT_EVENT


def test_separate_research_findings_about_one_tool_stay_different():
    assert _rel(
        "Clare Bryant utilizes Co-Scientist for genetic research",
        "Filippo Menolascina utilizes Co-Scientist for liver disease research",
    ) == EventRelationship.DIFFERENT_EVENT


def test_a_launch_and_a_migration_of_the_same_platform_stay_different():
    assert _rel(
        "Amazon Bedrock AgentCore launches an enhanced runtime for agents",
        "Clinic migrates agents to the Amazon Bedrock AgentCore runtime",
    ) == EventRelationship.DIFFERENT_EVENT


def test_same_organization_with_different_launches_stays_different():
    assert _rel(
        "OpenAI launches an ultrafast API tier for GPT-5.6 Sol",
        "OpenAI launches GPT-5.6 Cyber for cybersecurity work",
    ) == EventRelationship.DIFFERENT_EVENT


def test_marker_conflict_and_contrasting_claims_stay_different():
    assert _rel("H200 production expands", "B200 production expands") == EventRelationship.DIFFERENT_EVENT
    assert _rel("H200 production on track", "H200 production behind") == EventRelationship.DIFFERENT_EVENT
