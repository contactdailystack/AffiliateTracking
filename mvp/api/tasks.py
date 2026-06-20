"""Celery integration point (MVP stub).

We keep task wiring minimal so the API is usable even if worker isn't running.
"""

from typing import Any, Optional
from uuid import UUID
from .celery_client import celery_app


def enqueue_scan_project(
    scan_id: UUID,
    project_id: UUID,
    scan_variants: Optional[list[dict[str, Any]]] = None,
):
    # task name must match worker task.
    return celery_app.send_task(
        "mvp.worker.tasks.scan_project",
        kwargs={
            "scan_id": str(scan_id),
            "project_id": str(project_id),
            "scan_variants": scan_variants or [],
        },
        queue="scans",
    )

