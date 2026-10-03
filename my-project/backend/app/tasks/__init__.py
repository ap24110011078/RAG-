"""Tasks package for dispatching background jobs from backend services.

Task: T015
Spec: plan.md §2 (app/tasks/).

Exports the client-side Celery application instance.
"""

from app.tasks.celery_app import celery_client, get_celery_client

__all__ = [
    "celery_client",
    "get_celery_client",
]
