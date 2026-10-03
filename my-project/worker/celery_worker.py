"""Celery worker bootstrap with shared environment configuration.

Task: T015
Spec: FR-004, FR-026, plan.md §9 (Background Worker Architecture).

Initializes the Celery worker application with Redis broker and result backend,
production concurrency and serialization settings, and task discovery.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure backend package (app.*) and worker tasks (tasks.*) are resolvable
BACKEND_PATH = Path(__file__).resolve().parent.parent / "backend"
WORKER_PATH = Path(__file__).resolve().parent

if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

if str(WORKER_PATH) not in sys.path:
    sys.path.insert(0, str(WORKER_PATH))

from celery import Celery  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402

configure_logging()
logger = get_logger(__name__)

celery_app = Celery(
    "rag_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "tasks.document_processing",
        "tasks.run_evaluation",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,
)

logger.info(
    "celery_worker_configured",
    app_name=celery_app.main,
    broker=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    environment=settings.environment,
)

if __name__ == "__main__":
    celery_app.start()
