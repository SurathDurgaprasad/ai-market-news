"""
Phase 1A invariant: "Overlapping cycles must not create duplicate events."

Verified (not assumed) that this already holds via APScheduler's own
job defaults — scheduler.py's add_job() call never overrides them:

    job_defaults = {'misfire_grace_time': 1, 'coalesce': True, 'max_instances': 1}

max_instances=1 means APScheduler will not start a second
run_ingestion_cycle while one is still executing — a late-finishing
cycle causes the next trigger to be skipped (logged, not queued), not
run concurrently. coalesce=True means multiple missed fire times (e.g.
after the process was suspended) collapse into a single run rather than
firing back-to-back.

This test exists so a future change to IngestionScheduler.start()'s
add_job() call — e.g. someone raising max_instances to "let ingestion
run faster" — cannot silently regress this invariant without a test
failing to explain why.
"""
from app.core.scheduler import IngestionScheduler


def test_ingestion_job_does_not_allow_overlapping_instances():
    scheduler = IngestionScheduler()
    scheduler.start()
    try:
        job = scheduler.scheduler.get_job("ingestion_cycle")
        assert job is not None
        assert job.max_instances == 1, (
            "max_instances must stay 1 — overlapping ingestion cycles risk duplicate "
            "canonical events from concurrent, uncoordinated pipeline runs."
        )
        assert job.coalesce is True, (
            "coalesce must stay True — missed fire times should collapse into one run, "
            "not queue up and fire back-to-back."
        )
    finally:
        scheduler.stop()
