import uuid
from sqlalchemy import Column, String, Text, Integer, JSON, ForeignKey, DateTime, Float
from sqlalchemy.types import Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
from app.core.config import settings

try:
    if settings.get_database_url().startswith("sqlite"):
        raise ImportError("SQLite does not support pgvector")
    from pgvector.sqlalchemy import Vector
    VectorType = Vector(1536)
except (ImportError, Exception):
    VectorType = JSON

class Event(Base):
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    headline = Column(String, nullable=False)
    short_summary = Column(String, nullable=False)
    what_changed = Column(Text, nullable=True)
    # NOTE: why_it_matters is intentionally removed per PRD — no editorial commentary
    importance_score = Column(Integer, default=0)
    importance_reasoning = Column(JSON, nullable=True)
    # Entities extracted by LLM: organizations, products, people (e.g. ["OpenAI", "GPT-4o"])
    entities = Column(JSON, default=list, nullable=True)
    mentioned_entities = Column(JSON, default=list, nullable=True)
    citations = Column(JSON, default=list, nullable=True)
    image_url = Column(String, nullable=True)
    # Canonical source URL — always the clean article URL, never the dedup-modified version
    article_url = Column(String, nullable=True)
    official_source_name = Column(String, nullable=True)
    # When the underlying event actually occurred (from source publication time)
    event_time = Column(DateTime(timezone=True), index=True, nullable=True)
    embedding = Column(VectorType, nullable=True)
    primary_source_id = Column(Uuid, ForeignKey("source.id"), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    superseded_by_id = Column(Uuid, ForeignKey("event.id"), index=True, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    # Timestamp semantics:
    #   event_time  = real-world occurrence (article published_at)
    #   created_at  = when this canonical Event row was inserted (ingestion)
    #   updated_at  = last ORM update of this row
    # Dashboard cards display event_time (fallback created_at).
    # /events/new_count uses created_at so newly discovered old articles count as new,
    # while extra sources on an existing event do not.

    primary_source = relationship("Source")
    article_links = relationship("EventArticle", back_populates="event")

class EventArticle(Base):
    event_id = Column(Uuid, ForeignKey("event.id"), primary_key=True)
    article_id = Column(Uuid, ForeignKey("article.id"), primary_key=True)
    similarity_score = Column(Float, nullable=True)
    link_type = Column(String, default="supporting") # primary, supporting, additional

    event = relationship("Event", back_populates="article_links")
    article = relationship("Article", back_populates="event_links")
