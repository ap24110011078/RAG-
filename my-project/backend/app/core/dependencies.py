"""Core dependencies re-exported for module consistency.

Task: T013, T018
Spec: plan.md §2 (app/core/dependencies.py), §4 (authorization).

This module re-exports shared dependencies, validation utilities, and authorization
helpers from ``app.api.dependencies`` so imports from either location work seamlessly.
"""

from app.api.dependencies import (
    PaginationParams,
    get_conversation_for_user,
    get_current_active_user,
    get_current_user,
    get_db_session,
    get_document_for_user,
    get_owned_conversation,
    get_owned_document,
    get_pagination,
    oauth2_scheme,
    validate_file_upload,
    validate_search_query,
    validate_uuid,
    verify_resource_ownership,
)

__all__ = [
    "PaginationParams",
    "get_conversation_for_user",
    "get_current_active_user",
    "get_current_user",
    "get_db_session",
    "get_document_for_user",
    "get_owned_conversation",
    "get_owned_document",
    "get_pagination",
    "oauth2_scheme",
    "validate_file_upload",
    "validate_search_query",
    "validate_uuid",
    "verify_resource_ownership",
]
