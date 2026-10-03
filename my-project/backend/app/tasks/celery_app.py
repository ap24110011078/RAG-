"""Celery client for dispatching asynchronous background tasks from backend services.

Task: T015
Spec: plan.md §2 (app/tasks/celery_app.py).

Provides a lightweight Celery client instance configured with the shared Redis
broker and result backend, allowing FastAPI services to enqueue tasks via
send_task() without importing worker runtime dependencies.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

# Client-side Celery application instance used for dispatching tasks
celery_client = Celery(
    "rag_backend_client",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_client.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
)


def get_celery_client() -> Celery:
    """Return the client-side Celery application instance for task dispatching."""
    return celery_client
