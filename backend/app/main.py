from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.core.logger import setup_logging

setup_logging()

from contextlib import asynccontextmanager
from app.core.scheduler import scheduler
from app.core.runtime import is_test_runtime
from app.core.providers.llm import (
    resolve_llm_mode,
    LLM_UNAVAILABLE,
    configured_llm_provider_name,
)
from app.db.session import engine
from app.db.base_class import Base

import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    mode = resolve_llm_mode()
    provider_name = configured_llm_provider_name()
    logging.getLogger(__name__).info(
        "API startup llm_mode=%s llm_provider=%s test_runtime=%s scheduler=%s",
        mode,
        provider_name,
        is_test_runtime(),
        not is_test_runtime(),
    )
    if mode == LLM_UNAVAILABLE:
        logging.getLogger(__name__).error(
            "No usable production LLM (LLM_PROVIDER=%s). Ingestion is blocked; "
            "the API will still serve stored events.",
            provider_name,
        )
    if not is_test_runtime():
        Base.metadata.create_all(bind=engine)
        from app.db.session import ensure_sqlite_columns
        ensure_sqlite_columns(engine)
        scheduler.start()
    yield
    if not is_test_runtime():
        scheduler.stop()

app = FastAPI(
    title="AI World Intelligence Platform API",
    description="Internal API for the AI World Intelligence Platform dashboard and ingestion pipeline.",
    version="1.0.0",
    lifespan=lifespan
)

from app.core.config import settings

# No wildcard + no credentials: this API has no cookie/session auth
# (confirmed by absence of any auth module — docs/ARCHITECTURE.md §5), so
# there is nothing for a credentialed cross-origin request to steal today.
# Still: an explicit allowlist, not "*", both because "*" + credentials is
# a known-bad combination the moment auth is ever added, and because it's
# no harder to configure correctly from the start. See
# docs/RED_TEAM_REPORT.md CORS-01.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.router import api_router

@app.get("/api/health")
async def health_check():
    from app.core.providers.llm import resolve_llm_mode, LLM_UNAVAILABLE, configured_llm_provider_name
    from app.core.runtime import is_test_runtime
    mode = resolve_llm_mode()
    return {
        "status": "degraded" if mode == LLM_UNAVAILABLE else "ok",
        "service": "AI World Intelligence Platform API",
        "llm_mode": mode,
        "llm_provider": "test" if mode == "test" else configured_llm_provider_name(),
        "test_runtime": is_test_runtime(),
        "scheduler_enabled": not is_test_runtime(),
    }

app.include_router(api_router, prefix="/api/v1")
