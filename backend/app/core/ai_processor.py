from pydantic import BaseModel, Field
from typing import List, Optional

class EventClassification(BaseModel):
    tags: List[str] = Field(description="List of relevant tags like 'LLM', 'GPU', 'Open Source'")
    categories: List[str] = Field(description="High-level categories like 'Model Release', 'Funding'")
    entities: List[str] = Field(
        description="Legacy combined entity list. Prefer primary_entities.",
        default_factory=list,
    )
    primary_entities: List[str] = Field(
        description="1-6 organizations/products/people the event is ABOUT, not every mention.",
        default_factory=list,
    )
    mentioned_entities: List[str] = Field(
        description="Additional mentioned names, already deduplicated.",
        default_factory=list,
    )
    event_kind: str = Field(
        default="other",
        description="One of: model_release, model_family, capability, hardware_platform, funding, acquisition, partnership, security_incident, research, benchmark, open_source_release, tool_update, migration, maintenance, other",
    )
    technical_change_scope: str = Field(
        default="product",
        description="narrow | product | platform | ecosystem",
    )
    security_impact: str = Field(
        default="none",
        description="none | limited | significant. significant = RCE, account takeover, sandbox escape, widely deployed vulnerability.",
    )
    importance_score: int = Field(
        ge=0,
        le=100,
        description="Score from 0-100. 0 means drop (noise/injection). 1-100 is global AI ecosystem impact.",
    )
    importance_reasoning: str = Field(description="Brief reasoning for the importance score")

class SourceGroundedSummary(BaseModel):
    headline: str = Field(description="A concise, factual headline for the event. State what happened, not editorial spin.")
    short_summary: str = Field(description="1-2 factual sentences summarizing the event strictly based on the source text. State WHAT happened and WHAT technically changed. No editorial filler.")
    what_changed: str = Field(description="Newline-separated bullet points of what specifically changed or was released. Use ONLY facts from the article. No 'why it matters' commentary.")
    citations: List[str] = Field(
        description="1-3 verbatim contiguous quotes copied from the article (20-240 characters each) that support short_summary. Empty only if the article has no usable quote.",
        default_factory=list,
    )

def get_event_classification(article_content: str, provider=None) -> Optional[EventClassification]:
    """
    Uses injected LLM provider to classify an article and assign an importance score.
    """
    if not provider:
        from app.core.providers.llm import get_llm_provider
        provider = get_llm_provider()
        
    return provider.classify_event(article_content)

def generate_source_grounded_summary(articles_content: str, provider=None) -> Optional[SourceGroundedSummary]:
    """
    Generates a consolidated summary from one or multiple articles using injected LLM provider.
    """
    if not provider:
        from app.core.providers.llm import get_llm_provider
        provider = get_llm_provider()
        
    return provider.summarize_event(articles_content)
