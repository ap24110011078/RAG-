"""Application exception classes and centralized error handling.

Task: T013
Spec: FR-001, FR-026, plan.md §4 (error response schemas & exception handling).

This module defines domain-specific exception classes and registers centralized
FastAPI exception handlers to return consistent, structured JSON error responses.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.core.security import InvalidTokenError
from app.services.auth_service import (
    AuthenticationError,
    DuplicateEmailError,
    InactiveUserError,
    InvalidCredentialsError,
)

logger = get_logger(__name__)


# ============================================================================
# Error Response Schemas (Pydantic v2)
# ============================================================================


class ErrorDetailItem(BaseModel):
    """Structured detail for a single validation issue."""

    loc: list[str | int] = Field(default_factory=list)
    msg: str
    type: str = "value_error"


class ErrorResponse(BaseModel):
    """Standardized error response payload matching FastAPI convention.

    All error responses provide a ``detail`` field that contains either a
    descriptive string, a dictionary, or a list of validation error items.
    """

    detail: str | list[dict[str, Any]] | list[str] | dict[str, Any]
    error_code: str | None = None

    model_config = {"extra": "allow"}


# ============================================================================
# Base Application Exception
# ============================================================================


class AppException(Exception):
    """Base exception for all application domain errors.

    Subclasses specify a default ``status_code`` and ``error_code`` which are
    mapped automatically by the centralized exception handler.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_SERVER_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        detail: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        self.detail = detail if detail is not None else message
        self.headers = headers or {}


# ============================================================================
# Specific Domain Exceptions
# ============================================================================


class ValidationError(AppException):
    """Raised when request payload or parameter validation fails."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"


class BadRequestError(AppException):
    """Raised when a request is malformed or violates business rules."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "BAD_REQUEST"


class AppAuthenticationError(AppException):
    """Raised when authentication credentials or token are invalid."""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"

    def __init__(
        self,
        message: str = "Could not validate credentials",
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        default_headers = {"WWW-Authenticate": "Bearer"}
        if headers:
            default_headers.update(headers)
        super().__init__(message, headers=default_headers, **kwargs)


class AuthorizationError(AppException):
    """Raised when the user lacks permission for the requested resource."""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"


class NotFoundError(AppException):
    """Raised when a requested entity does not exist."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ResourceNotFoundError(NotFoundError):
    """Raised when a specific resource by ID is not found."""

    def __init__(
        self,
        resource_type: str = "Resource",
        resource_id: Any = None,
        message: str | None = None,
    ) -> None:
        msg = message or (
            f"{resource_type} with ID '{resource_id}' not found"
            if resource_id
            else f"{resource_type} not found"
        )
        super().__init__(msg)
        self.resource_type = resource_type
        self.resource_id = resource_id


class ConflictError(AppException):
    """Raised when a resource conflict or duplicate state occurs."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


class DuplicateResourceError(ConflictError):
    """Raised when attempting to create a resource that already exists."""

    def __init__(
        self,
        resource_type: str = "Resource",
        identifier: Any = None,
        message: str | None = None,
    ) -> None:
        msg = message or (
            f"{resource_type} with identifier '{identifier}' already exists"
            if identifier
            else f"{resource_type} already exists"
        )
        super().__init__(msg)


class FileValidationError(BadRequestError):
    """Raised when an uploaded document file fails format/size validation."""

    error_code = "INVALID_FILE"


class DocumentProcessingError(AppException):
    """Raised when document ingestion, parsing, or chunking fails."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "PROCESSING_ERROR"


class RateLimitExceededError(AppException):
    """Raised when request rate limits are exceeded."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"


class ServiceUnavailableError(AppException):
    """Raised when a downstream dependency (database, Redis, LLM) is unavailable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "SERVICE_UNAVAILABLE"


class StorageError(AppException):
    """Base exception for file storage operations."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "STORAGE_ERROR"


class StorageFileNotFoundError(NotFoundError):
    """Raised when a requested file cannot be found in storage."""

    error_code = "STORAGE_FILE_NOT_FOUND"

    def __init__(self, file_path_or_key: str, message: str | None = None) -> None:
        msg = message or f"Stored file not found: '{file_path_or_key}'"
        super().__init__(msg)
        self.file_path_or_key = file_path_or_key


class StoragePathTraversalError(BadRequestError):
    """Raised when a storage path or key contains unsafe traversal sequences."""

    error_code = "PATH_TRAVERSAL_DETECTED"

    def __init__(self, path: str, message: str | None = None) -> None:
        msg = message or f"Unsafe storage path detected: '{path}'"
        super().__init__(msg)
        self.path = path


# ============================================================================
# Centralized Exception Handlers Registration
# ============================================================================


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the FastAPI application.

    Ensures consistent JSON error responses across all endpoints for:
    - Domain AppException subclasses (400, 401, 403, 404, 409, 422, 503)
    - T011 AuthService errors (DuplicateEmailError -> 409, InvalidCredentialsError -> 401, InactiveUserError -> 403)
    - T011 Security errors (InvalidTokenError -> 401)
    - FastAPI/Pydantic RequestValidationError (422)
    - Starlette/FastAPI HTTPException
    - Unhandled Exception (500)
    """

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "app_exception",
            path=request.url.path,
            method=request.method,
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers or None,
        )

    @app.exception_handler(DuplicateEmailError)
    async def handle_duplicate_email(
        request: Request, exc: DuplicateEmailError
    ) -> JSONResponse:
        logger.warning("duplicate_email_error", path=request.url.path, message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc) or "An account with this email already exists"},
        )

    @app.exception_handler(InvalidCredentialsError)
    async def handle_invalid_credentials(
        request: Request, exc: InvalidCredentialsError
    ) -> JSONResponse:
        logger.warning("invalid_credentials_error", path=request.url.path)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid email or password"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(InactiveUserError)
    async def handle_inactive_user(
        request: Request, exc: InactiveUserError
    ) -> JSONResponse:
        logger.warning("inactive_user_error", path=request.url.path, message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": str(exc) or "User account is inactive"},
        )

    @app.exception_handler(InvalidTokenError)
    async def handle_invalid_token(
        request: Request, exc: InvalidTokenError
    ) -> JSONResponse:
        logger.warning("invalid_token_error", path=request.url.path, message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired access token"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(AuthenticationError)
    async def handle_auth_error(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        logger.warning("authentication_error", path=request.url.path, message=str(exc))
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "request_validation_error",
            path=request.url.path,
            method=request.method,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        headers = getattr(exc, "headers", None)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(
            "unhandled_server_error",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
