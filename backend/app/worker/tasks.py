from app.worker.celery_app import celery_app
import logging

logger = logging.getLogger(__name__)

@celery_app.task
def poll_active_sources():
    """
    Scheduled task that polls the database for all active sources
    and dispatches individual fetch tasks.
    """
    logger.info("Starting to poll active sources...")
    # TODO: Connect to DB, fetch active sources, and call fetch_source.delay(source_id)
    pass

@celery_app.task
def fetch_source(source_id: str):
    """
    Task to fetch data for a single source.
    """
    logger.info(f"Fetching source {source_id}")
    # TODO: Fetch logic (RSS parsing, API requests, etc.)
    # TODO: Deduplication and pipeline initiation
    pass
