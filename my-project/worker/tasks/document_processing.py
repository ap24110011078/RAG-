"""Document processing Celery task skeleton.

Task: T016
Spec: FR-004, FR-005, plan.md §5, §9 (Document ingestion task skeleton).

This module defines the Celery task skeleton for background document
ingestion. Full parsing, chunking, embedding, and pgvector persistence
pipelines will be implemented in Phase 4 (T042/T044).
"""

from __future__ import annotations

from typing import Any

from celery import Task
from celery_worker import celery_app

from app.core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="tasks.document_processing.process_document",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_document(
    self: Task,
    document_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Process an uploaded document in the background (Task Skeleton).

    Args:
        document_id: Unique UUID identifier string for the document.
        **kwargs: Additional optional processing parameters.

    Returns:
        Dict containing task execution outcome and metadata placeholder.
    """
    doc_id_str = str(document_id)
    task_id = self.request.id if getattr(self, "request", None) else None

    logger.info(
        "document_processing_task_started",
        task_id=task_id,
        document_id=doc_id_str,
    )

    # NOTE: Full ingestion pipeline (PDF parsing, OCR, chunking, embeddings,
    # and pgvector persistence) will be implemented in T042 / T044.

    logger.info(
        "document_processing_task_completed",
        task_id=task_id,
        document_id=doc_id_str,
    )

    return {
        "status": "QUEUED_SKELETON",
        "document_id": doc_id_str,
        "task_id": task_id,
    }

