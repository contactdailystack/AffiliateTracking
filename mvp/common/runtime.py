from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    app_name: str = os.getenv("APP_NAME", "Affiliate Tracking Integrity Monitoring")
    app_env: str = os.getenv("APP_ENV", "development")
    app_version: str = os.getenv("APP_VERSION", "dev")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    gunicorn_workers: int = int(os.getenv("GUNICORN_WORKERS", "2"))
    gunicorn_timeout: int = int(os.getenv("GUNICORN_TIMEOUT", "120"))
    gunicorn_bind: str = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
    celery_log_level: str = os.getenv("CELERY_LOG_LEVEL", "INFO")
    celery_concurrency: int = int(os.getenv("CELERY_CONCURRENCY", "4"))
    celery_prefetch_multiplier: int = int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1"))
    celery_max_tasks_per_child: int = int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "100"))


runtime = RuntimeConfig()
