"""Shared FastAPI request dependencies and validation utilities.

Task: T013
Spec: FR-001, FR-026, FR-028, plan.md §4 (API dependencies & validation).

This module provides reusable dependencies for:
- Database session injection
- OAuth2 Bearer token extraction and user resolution
- Pagination parameter validation
- File upload and parameter validation helpers
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, Path, Query
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppAuthenticationError,
    AuthorizationError,
    BadRequestError,
    FileValidationError,
    ResourceNotFoundError,
    ValidationError,
)
from app.core.security import InvalidTokenError
from app.db.models import Conversation, Document, User
from app.db.session import get_db_session
from app.services.auth_service import InactiveUserError, auth_service

# ---------------------------------------------------------------------------
# OAuth2 scheme — extracts the Bearer token from the Authorization header.
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login",
    description="Bearer token authentication for protected endpoints.",
)


# ===========================================================================
# Pagination Dependency
# ===========================================================================


class PaginationParams(BaseModel):
    """Validated pagination parameters for list endpoints."""

    page: int = Field(default=1, ge=1, description="1-based page number")
    page_size: int = Field(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    )

    @property
    def offset(self) -> int:
        """Calculate zero-based database offset."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Alias for page_size used in SQL queries."""
        return self.page_size


async def get_pagination(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (1-100)"
    ),
) -> PaginationParams:
    """Dependency that parses and validates query pagination parameters."""
    return PaginationParams(page=page, page_size=page_size)


# ===========================================================================
# Authentication / User Dependencies
# ===========================================================================


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """Resolve the Bearer token to an authenticated database user.

    Raises:
        AppAuthenticationError: If the token is invalid, expired, or the user
                                does not exist in the database (HTTP 401).
        AuthorizationError:     If the user account is inactive (HTTP 403).
    """
    try:
        user = await auth_service.get_user_from_token(db, token)
        return user
    except InvalidTokenError as exc:
        raise AppAuthenticationError(
            message=str(exc) or "Invalid or expired access token",
        ) from exc
    except InactiveUserError as exc:
        raise AuthorizationError(
            message=str(exc) or "User account is inactive",
        ) from exc


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Verify that the currently authenticated user account is active.

    Raises:
        AuthorizationError: If the user's ``is_active`` flag is False (HTTP 403).
    """
    if not current_user.is_active:
        raise AuthorizationError("User account is inactive")
    return current_user


# ===========================================================================
# Request Validation Utilities
# ===========================================================================


def validate_uuid(value: str | uuid.UUID, field_name: str = "id") -> uuid.UUID:
    """Validate and parse a string into a UUID.

    Raises:
        ValidationError: If the value cannot be parsed as a valid UUID.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(
            f"Invalid {field_name}: '{value}' is not a valid UUID",
            detail={"field": field_name, "value": str(value), "error": "invalid_uuid"},
        ) from exc


def validate_file_upload(
    filename: str,
    content_type: str | None = None,
    file_size_bytes: int | None = None,
    *,
    allowed_extensions: tuple[str, ...] = (".pdf",),
    allowed_mime_types: tuple[str, ...] = ("application/pdf",),
    max_size_bytes: int = 50 * 1024 * 1024,  # 50 MB default
) -> None:
    """Validate uploaded document metadata against size and format constraints.

    Spec: FR-002, FR-028 (file validation, rejecting invalid document types).

    Raises:
        FileValidationError: If the file extension, MIME type, or size is invalid.
    """
    if not filename or not filename.strip():
        raise FileValidationError("Filename must not be empty")

    lower_name = filename.strip().lower()
    if not any(lower_name.endswith(ext) for ext in allowed_extensions):
        allowed_str = ", ".join(allowed_extensions)
        raise FileValidationError(
            f"Unsupported file type. Allowed formats: {allowed_str}"
        )

    if content_type:
        clean_mime = content_type.split(";")[0].strip().lower()
        if clean_mime not in allowed_mime_types:
            raise FileValidationError(
                f"Invalid MIME type '{content_type}'. Expected one of: {', '.join(allowed_mime_types)}"
            )

    if file_size_bytes is not None:
        if file_size_bytes <= 0:
            raise FileValidationError("Uploaded file is empty")
        if file_size_bytes > max_size_bytes:
            max_mb = max_size_bytes / (1024 * 1024)
            raise FileValidationError(
                f"File size exceeds maximum allowed limit of {max_mb:.0f} MB"
            )


def validate_search_query(
    query: str,
    *,
    min_length: int = 1,
    max_length: int = 2000,
) -> str:
    """Validate and sanitize a natural language search/question query.

    Raises:
        BadRequestError: If the query is empty, whitespace-only, or exceeds max length.
    """
    if not query or not query.strip():
        raise BadRequestError("Query string must not be empty")
    cleaned = query.strip()
    if len(cleaned) < min_length:
        raise BadRequestError(
            f"Query must be at least {min_length} character(s) long"
        )
    if len(cleaned) > max_length:
        raise BadRequestError(
            f"Query exceeds maximum allowed length of {max_length} characters"
        )
    return cleaned


# ===========================================================================
# Authorization / Ownership Dependencies (Task T018)
# ===========================================================================


def verify_resource_ownership(
    resource: Any,
    user_id: uuid.UUID,
    owner_field: str = "owner_id",
    resource_type: str = "Resource",
) -> None:
    """Verify that a database entity is owned by the specified user.

    Args:
        resource: ORM model instance (e.g. Document, Conversation)
        user_id: UUID of the authenticated user
        owner_field: Field name storing owner UUID (e.g. 'owner_id', 'user_id')
        resource_type: Human-readable entity name for error messages

    Raises:
        ResourceNotFoundError: If resource is None (HTTP 404)
        AuthorizationError: If resource is owned by a different user (HTTP 403)
    """
    if resource is None:
        raise ResourceNotFoundError(resource_type=resource_type)

    actual_owner_id = getattr(resource, owner_field, None)
    if actual_owner_id is not None and actual_owner_id != user_id:
        raise AuthorizationError(
            f"You do not have permission to access this {resource_type.lower()}"
        )


async def get_document_for_user(
    db: AsyncSession,
    document_id: uuid.UUID | str,
    user_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> Document:
    """Query a document by ID and verify ownership for the specified user.

    Args:
        db: Database async session
        document_id: Document UUID or UUID string
        user_id: Authenticated user UUID
        include_deleted: Whether to allow soft-deleted documents

    Returns:
        The verified Document ORM model instance.

    Raises:
        ValidationError: If document_id is an invalid UUID format (HTTP 422)
        ResourceNotFoundError: If document does not exist (HTTP 404)
        AuthorizationError: If document is owned by another user (HTTP 403)
    """
    parsed_id = validate_uuid(document_id, field_name="document_id")

    # Fetch document by primary key
    result = await db.execute(select(Document).where(Document.id == parsed_id))
    document = result.scalar_one_or_none()

    if document is None:
        raise ResourceNotFoundError(resource_type="Document", resource_id=str(parsed_id))

    if document.owner_id != user_id:
        raise AuthorizationError("You do not have permission to access this document")

    if not include_deleted and document.deleted_at is not None:
        raise ResourceNotFoundError(resource_type="Document", resource_id=str(parsed_id))

    return document


async def get_owned_document(
    document_id: Annotated[uuid.UUID, Path(description="Document unique identifier")],
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Document:
    """FastAPI path dependency that resolves and authorizes a Document by path parameter.

    Usage in future endpoints::

        @router.get("/documents/{document_id}")
        async def get_document(doc: Document = Depends(get_owned_document)):
            return doc

    Raises:
        ResourceNotFoundError: If document does not exist (HTTP 404)
        AuthorizationError: If document belongs to another user (HTTP 403)
    """
    return await get_document_for_user(db, document_id, current_user.id)


async def get_conversation_for_user(
    db: AsyncSession,
    conversation_id: uuid.UUID | str,
    user_id: uuid.UUID,
) -> Conversation:
    """Query a conversation by ID and verify ownership for the specified user.

    Args:
        db: Database async session
        conversation_id: Conversation UUID or UUID string
        user_id: Authenticated user UUID

    Returns:
        The verified Conversation ORM model instance.

    Raises:
        ValidationError: If conversation_id is an invalid UUID format (HTTP 422)
        ResourceNotFoundError: If conversation does not exist (HTTP 404)
        AuthorizationError: If conversation belongs to another user (HTTP 403)
    """
    parsed_id = validate_uuid(conversation_id, field_name="conversation_id")

    result = await db.execute(select(Conversation).where(Conversation.id == parsed_id))
    conversation = result.scalar_one_or_none()

    if conversation is None:
        raise ResourceNotFoundError(
            resource_type="Conversation", resource_id=str(parsed_id)
        )

    if conversation.user_id != user_id:
        raise AuthorizationError(
            "You do not have permission to access this conversation"
        )

    return conversation


async def get_owned_conversation(
    conversation_id: Annotated[
        uuid.UUID, Path(description="Conversation unique identifier")
    ],
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Conversation:
    """FastAPI path dependency that resolves and authorizes a Conversation by path parameter.

    Raises:
        ResourceNotFoundError: If conversation does not exist (HTTP 404)
        AuthorizationError: If conversation belongs to another user (HTTP 403)
    """
    return await get_conversation_for_user(db, conversation_id, current_user.id)

