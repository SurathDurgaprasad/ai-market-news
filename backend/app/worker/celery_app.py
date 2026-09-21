from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_routes = {
    "app.worker.tasks.*": {"queue": "main-queue"}
}

celery_app.conf.beat_schedule = {
    "poll-sources-every-20-mins": {
        "task": "app.worker.tasks.poll_active_sources",
        "schedule": 1200.0, # 20 minutes
    }
}
celery_app.conf.timezone = "UTC"
