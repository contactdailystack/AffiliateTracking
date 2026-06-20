# mvp/worker/beat_scheduler.py
"""Celery Beat scheduler: periodically queue scans for due projects."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .celery_app import celery_app
from .tasks import scan_project

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://mvp:mvp@localhost:5432/mvp",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@celery_app.task(name="mvp.worker.beat_scheduler.schedule_due_scans")
def schedule_due_scans():
    """Find projects that are due for a scan and enqueue them."""
    session = SessionLocal()
    try:
        # Ensure every project has a scan_schedules row
        _ensure_scan_schedules(session)

        # Find projects due for scanning
        now = datetime.now(timezone.utc)
        rows = session.execute(
            text(
                """
                SELECT
                    ss.project_id,
                    p.tenant_id,
                    p.scan_frequency_seconds,
                    ss.last_scheduled_at
                FROM scan_schedules ss
                JOIN projects p ON p.id = ss.project_id
                WHERE ss.enabled = true
                  AND (ss.next_due_at IS NULL OR ss.next_due_at <= :now)
                """
            ),
            {"now": now},
        ).mappings().all()

        for row in rows:
            project_id = str(row["project_id"])
            tenant_id = str(row["tenant_id"])
            freq = row["scan_frequency_seconds"] or 86400

            logger.info("Scheduling scan for project_id=%s", project_id)

            # Enqueue scan task
            celery_app.send_task(
                "mvp.worker.tasks.scan_project",
                kwargs={"project_id": project_id},
                queue="scans",
            )

            # Update schedule
            next_due = now + timedelta(seconds=freq)
            session.execute(
                text(
                    """
                    UPDATE scan_schedules
                    SET last_scheduled_at = :now,
                        next_due_at = :next_due,
                        updated_at = :now
                    WHERE project_id = :project_id
                    """
                ),
                {
                    "now": now,
                    "next_due": next_due,
                    "project_id": project_id,
                },
            )
            session.commit()

        return {"scheduled": len(rows)}
    except Exception:
        logger.exception("schedule_due_scans failed")
        raise
    finally:
        session.close()


def _ensure_scan_schedules(session):
    """Create scan_schedules rows for any project that doesn't have one yet."""
    session.execute(
        text(
            """
            INSERT INTO scan_schedules (id, project_id, enabled)
            SELECT gen_random_uuid(), p.id, true
            FROM projects p
            LEFT JOIN scan_schedules ss ON ss.project_id = p.id
            WHERE ss.id IS NULL
            """
        )
    )
    session.commit()
