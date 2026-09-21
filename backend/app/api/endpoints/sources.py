from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.db.session import get_db
from app.models.source import Source

router = APIRouter()

class SourceResponse(BaseModel):
    id: str
    name: str
    url: str
    tier: str
    health_status: str
    last_fetch_at: Optional[datetime] = None
    last_error_info: Optional[str] = None
    last_ingest_summary: Optional[str] = None
    consecutive_failures: int = 0
    polling_tier: Optional[str] = None
    enabled: bool
    
    model_config = ConfigDict(from_attributes=True)

@router.get("/", response_model=List[SourceResponse])
def get_sources(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100)
):
    sources = db.query(Source).offset(skip).limit(limit).all()
    
    # Map UUIDs to strings
    response_sources = []
    for source in sources:
        response_sources.append(SourceResponse(
            id=str(source.id),
            name=source.name,
            url=source.url,
            tier=source.tier,
            health_status=source.health_status,
            last_fetch_at=source.last_fetch_at,
            last_error_info=source.last_error_info,
            last_ingest_summary=source.last_ingest_summary,
            consecutive_failures=source.consecutive_failures or 0,
            polling_tier=source.polling_tier,
            enabled=source.enabled
        ))
    return response_sources
