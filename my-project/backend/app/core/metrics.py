"""Performance metrics for HTTP requests and background worker tasks.

Task: T017
Spec: FR-026, plan.md §2 (app/core/metrics.py), §4 (health & metrics).

Provides utilities for:
- Measuring and recording HTTP request duration and throughput
- Measuring and recording basic Celery worker task execution
- Prometheus metrics collectors with fallback in-memory registry
- Context managers and helpers for timing measurements
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Generator

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)

from app.core.logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# HTTP Request Metrics (Prometheus)
# ============================================================================

# Default bucket distribution for HTTP latency (in seconds: 5ms to 10s)
HTTP_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.075,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    2.5,
    5.0,
    10.0,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path", "status_code"],
    buckets=HTTP_DURATION_BUCKETS,
)

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed",
    ["method", "path", "status_code"],
)

HTTP_REQUESTS_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Number of HTTP requests currently being processed",
    ["method"],
)

# ============================================================================
# Basic Worker / Task Metrics (Prometheus)
# ============================================================================

TASK_DURATION_BUCKETS = (
    0.01,
    0.05,
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)

CELERY_TASKS_SUBMITTED_TOTAL = Counter(
    "celery_tasks_submitted_total",
    "Total count of Celery tasks dispatched from backend",
    ["task_name"],
)

CELERY_TASKS_PROCESSED_TOTAL = Counter(
    "celery_tasks_processed_total",
    "Total count of Celery tasks processed by workers",
    ["task_name", "status"],
)

CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds",
    "Celery task execution duration in seconds",
    ["task_name"],
    buckets=TASK_DURATION_BUCKETS,
)


# ============================================================================
# Request Timing Utilities
# ============================================================================


def record_request_metrics(
    method: str,
    path: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record timing and throughput metrics for an HTTP request.

    Args:
        method: HTTP verb (GET, POST, etc.)
        path: Normalized route path or path template
        status_code: Response HTTP status code
        duration_seconds: Elapsed request time in seconds
    """
    normalized_method = method.upper()
    status_str = str(status_code)

    HTTP_REQUEST_DURATION_SECONDS.labels(
        method=normalized_method,
        path=path,
        status_code=status_str,
    ).observe(duration_seconds)

    HTTP_REQUESTS_TOTAL.labels(
        method=normalized_method,
        path=path,
        status_code=status_str,
    ).inc()

    logger.info(
        "http_request_timing",
        method=normalized_method,
        path=path,
        status_code=status_code,
        duration_ms=round(duration_seconds * 1000, 2),
    )


@contextmanager
def time_request(
    method: str,
    path: str,
) -> Generator[dict[str, Any], None, None]:
    """Context manager for measuring request latency with in-flight tracking.

    Usage::

        with time_request("POST", "/api/auth/login") as ctx:
            response = await call_next(request)
            ctx["status_code"] = response.status_code

    Args:
        method: HTTP method string
        path: Route path string

    Yields:
        Mutable context dictionary where the caller sets ``status_code``.
    """
    normalized_method = method.upper()
    HTTP_REQUESTS_IN_FLIGHT.labels(method=normalized_method).inc()
    start_time = time.perf_counter()
    context: dict[str, Any] = {"status_code": 200}

    try:
        yield context
    finally:
        duration = time.perf_counter() - start_time
        HTTP_REQUESTS_IN_FLIGHT.labels(method=normalized_method).dec()
        status_code = context.get("status_code", 500)
        record_request_metrics(
            method=normalized_method,
            path=path,
            status_code=status_code,
            duration_seconds=duration,
        )


# ============================================================================
# Worker Metric Utilities
# ============================================================================


def record_task_submitted(task_name: str) -> None:
    """Record that a task was dispatched to the Celery broker.

    Args:
        task_name: Full task name (e.g. ``tasks.document_processing.process_document``)
    """
    CELERY_TASKS_SUBMITTED_TOTAL.labels(task_name=task_name).inc()
    logger.info("task_submitted_metric", task_name=task_name)


def record_task_completed(
    task_name: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record execution completion and duration for a worker task.

    Args:
        task_name: Full task name string
        status: Task outcome status (e.g. ``SUCCESS``, ``FAILURE``)
        duration_seconds: Task run time in seconds
    """
    normalized_status = status.upper()
    CELERY_TASKS_PROCESSED_TOTAL.labels(
        task_name=task_name,
        status=normalized_status,
    ).inc()

    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name).observe(duration_seconds)

    logger.info(
        "task_completed_metric",
        task_name=task_name,
        status=normalized_status,
        duration_ms=round(duration_seconds * 1000, 2),
    )


@contextmanager
def time_task(
    task_name: str,
) -> Generator[dict[str, Any], None, None]:
    """Context manager for measuring worker task execution duration.

    Usage::

        with time_task("tasks.document_processing.process_document") as ctx:
            do_work()
            ctx["status"] = "SUCCESS"

    Args:
        task_name: Celery task name

    Yields:
        Mutable context dictionary where caller sets ``status``.
    """
    start_time = time.perf_counter()
    context: dict[str, Any] = {"status": "SUCCESS"}
    try:
        yield context
    except Exception:
        context["status"] = "FAILURE"
        raise
    finally:
        duration = time.perf_counter() - start_time
        status = context.get("status", "SUCCESS")
        record_task_completed(
            task_name=task_name,
            status=status,
            duration_seconds=duration,
        )


# ============================================================================
# Exposition / Summary
# ============================================================================


def get_metrics_snapshot(registry: CollectorRegistry = REGISTRY) -> bytes:
    """Generate Prometheus exposition text format bytes.

    Returns:
        Bytes payload in Prometheus format.
    """
    return generate_latest(registry)


def get_metrics_content_type() -> str:
    """Return the HTTP Content-Type for Prometheus metrics."""
    return CONTENT_TYPE_LATEST
