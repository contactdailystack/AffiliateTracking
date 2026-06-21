import os
import logging
from celery import Celery
from celery import signals

from common.observability import configure_logging
from common.runtime import runtime

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")

configure_logging(getattr(logging, runtime.celery_log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

celery_app = Celery(
    "affiliate_mvp",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_track_started=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    worker_prefetch_multiplier=runtime.celery_prefetch_multiplier,
    worker_max_tasks_per_child=runtime.celery_max_tasks_per_child,
)

celery_app.conf.task_routes = {
    "mvp.worker.tasks.scan_project": {"queue": "scans"},
}

# Register tasks so the worker discovers them by task name.
try:
    from tasks import scan_project  # noqa: F401
except ImportError:
    from mvp.worker.tasks import scan_project  # noqa: F401


@signals.task_prerun.connect
def _task_prerun(sender=None, task_id=None, task=None, **kwargs):
    logger.info("task_start name=%s task_id=%s", getattr(sender, "name", "unknown"), task_id)


@signals.task_postrun.connect
def _task_postrun(sender=None, task_id=None, state=None, **kwargs):
    logger.info("task_done name=%s task_id=%s state=%s", getattr(sender, "name", "unknown"), task_id, state)


@signals.task_failure.connect
def _task_failure(sender=None, task_id=None, exception=None, **kwargs):
    logger.exception(
        "task_failed name=%s task_id=%s error=%s",
        getattr(sender, "name", "unknown"),
        task_id,
        exception,
    )


