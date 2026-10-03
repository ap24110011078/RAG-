"""Database package — exports Base, ORM models, and session utilities."""

from app.db.base import Base
from app.db.models import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentSection,
    EvaluationCase,
    Message,
    User,
)

__all__ = [
    "Base",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentPage",
    "DocumentSection",
    "EvaluationCase",
    "Message",
    "User",
]

from app.db.session import async_session_factory, engine, get_db_session  # noqa: E402

__all__ += [
    "async_session_factory",
    "engine",
    "get_db_session",
]
