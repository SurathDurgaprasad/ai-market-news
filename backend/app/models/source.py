import uuid
from sqlalchemy import Column, String, Enum, Boolean, JSON, ForeignKey, DateTime, Integer
from sqlalchemy.types import Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import enum

class SourceTier(str, enum.Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    COMMUNITY = "COMMUNITY"

class SourceType(str, enum.Enum):
    API = "API"
    RSS = "RSS"

class Organization(Base):
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, index=True, nullable=False)
    domain = Column(String, nullable=True)

    sources = relationship("Source", back_populates="organization")

class Source(Base):
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    organization_id = Column(Uuid, ForeignKey("organization.id"), nullable=True)
    
    # PRD fields
    type = Column(String, default="rss") # rss, github, api, crawl
    tier = Column(String, default="secondary") # primary, secondary, community
    polling_tier = Column(String, default="medium") # high, medium, low
    enabled = Column(Boolean, default=True)
    health_status = Column(String, default="healthy") # healthy, degraded, failing, disabled
    last_error_info = Column(String, nullable=True)
    consecutive_failures = Column(Integer, default=0, nullable=False)

    last_fetch_at = Column(DateTime(timezone=True), nullable=True)
    last_failure_at = Column(DateTime(timezone=True), nullable=True)
    # Compact last-cycle counters: discovered/created/linked/rejected/duplicates
    last_ingest_summary = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    organization = relationship("Organization", back_populates="sources")
    articles = relationship("Article", back_populates="source")
