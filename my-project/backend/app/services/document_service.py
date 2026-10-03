"""Document service for document metadata, lifecycle, and task dispatching.

Task: T016
Spec: FR-004, plan.md §2 (app/services/document_service.py).

Provides the backend service interface for document operations and asynchronous
task dispatching to the Celery worker via the decoupled Celery client.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logging import get_logger
from app.tasks.celery_app import celery_client

logger = get_logger(__name__)

# Constant for the document processing task name across backend and worker
DOCUMENT_PROCESSING_TASK = "tasks.document_processing.process_document"


class DocumentService:
    """Service handling document business logic and worker task invocation."""

    def enqueue_document_processing(
        self,
        document_id: str | uuid.UUID,
        **task_kwargs: Any,
    ) -> str:
        """Enqueue an asynchronous document processing task to the worker.

        Dispatches the ``tasks.document_processing.process_document`` Celery task
        using the backend Celery client without importing worker runtime modules.

        Args:
            document_id: Unique UUID or UUID string of the uploaded document.
            **task_kwargs: Optional keyword arguments to pass to the task.

        Returns:
            The Celery task ID (str) assigned to the dispatched background job.
        """
        doc_id_str = str(document_id)
        logger.info(
            "dispatching_document_processing_task",
            document_id=doc_id_str,
            task_name=DOCUMENT_PROCESSING_TASK,
        )

        async_result = celery_client.send_task(
            DOCUMENT_PROCESSING_TASK,
            args=[doc_id_str],
            kwargs=task_kwargs if task_kwargs else None,
        )

        logger.info(
            "document_processing_task_dispatched",
            document_id=doc_id_str,
            task_id=async_result.id,
        )

        return str(async_result.id)


# Stateless singleton instance safe for dependency injection and service calls
document_service = DocumentService()


def enqueue_document_processing(
    document_id: str | uuid.UUID,
    **task_kwargs: Any,
) -> str:
    """Module-level convenience wrapper for enqueueing document processing."""
    return document_service.enqueue_document_processing(document_id, **task_kwargs)
