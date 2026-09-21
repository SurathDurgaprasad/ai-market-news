import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float
from sqlalchemy.types import Uuid
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base

class Article(Base):
    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id = Column(Uuid, ForeignKey("source.id"), nullable=False)
    url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    raw_content = Column(Text, nullable=True)
    body_excerpt = Column(String(500), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    hash = Column(String, index=True, nullable=True)
    image_url = Column(String, nullable=True)
    publisher_name = Column(String, nullable=True)

    source = relationship("Source", back_populates="articles")
    event_links = relationship("EventArticle", back_populates="article")
