"""ORM models for the RAG Document Intelligence chatbot.

Models defined here:
- User              — authenticated application user
- Document          — uploaded business document (PDF)
- DocumentPage      — per-page text extracted from a Document
- DocumentSection   — structural section / heading block within a Document
- DocumentChunk     — retrieval child chunk derived from a DocumentSection,
                      carries the pgvector embedding
- Conversation      — chat session belonging to a User, optionally document-scoped
- Message           — single turn within a Conversation
- EvaluationCase    — benchmark question used for quality regression testing

Design decisions
----------------
- SQLAlchemy 2.x typed declarative style (``Mapped`` / ``mapped_column``).
- UUIDs for all primary keys (generated Python-side for predictability).
- All ``status`` and ``role`` fields use Python ``enum.Enum`` with a
  ``VARCHAR`` column (not a PostgreSQL ENUM type) to keep migrations simpler.
- Soft-delete via ``deleted_at`` on ``Document`` (spec edge-case: deleted
  documents must stop contributing to retrieval without hard-deleting history).
- ``DocumentChunk.embedding`` uses the ``pgvector`` extension via the
  ``pgvector.sqlalchemy.Vector`` column type.
- JSON / JSONB columns store flexible metadata to avoid premature schema
  churn while the chunking and retrieval pipelines are still being built.
- ``__table_args__`` declares explicit indexes; additional vector indexes
  (ivfflat / hnsw) must be created by a migration once the embedding
  dimension is fixed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ============================================================================
# Enumerations
# ============================================================================


class DocumentStatus(str, enum.Enum):
    """Processing lifecycle of an uploaded document (FR-005)."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class MessageRole(str, enum.Enum):
    """Speaker role for a conversation Message (plan §8)."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class EvaluationStatus(str, enum.Enum):
    """Outcome of a single evaluation run (plan §evaluation)."""

    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"


# ============================================================================
# User
# ============================================================================


class User(Base):
    """Authenticated user who owns documents and conversations.

    Spec: FR-001, FR-029, Key Entities — User.
    Schema: plan.md §3 users table.
    """

    __tablename__ = "users"

    # Core identity
    email: Mapped[str] = mapped_column(
        String(320),  # RFC 5321 maximum
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r}>"


# ============================================================================
# Document
# ============================================================================


class Document(Base):
    """Uploaded business document (initially PDF-only).

    Spec: FR-002 – FR-006, FR-023 – FR-024, Key Entities — Document.
    Schema: plan.md §3 documents table.

    Soft-delete: ``deleted_at`` is set instead of hard-deleting rows so that
    historical conversation citations remain intact (spec edge-cases).
    """

    __tablename__ = "documents"

    __table_args__ = (
        # Duplicate detection (FR-003, FR-006): unique hash per owner.
        UniqueConstraint("owner_id", "content_hash", name="uq_documents_owner_hash"),
        # Fast listing per user, ordered by upload time.
        Index("ix_documents_owner_uploaded", "owner_id", "uploaded_at"),
        # Retrieval exclusion filter on status and soft-delete.
        Index("ix_documents_status_deleted", "status", "deleted_at"),
    )

    # ------------------------------------------------------------------ #
    # Ownership                                                            #
    # ------------------------------------------------------------------ #
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # File identity                                                        #
    # ------------------------------------------------------------------ #
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest
        nullable=False,
        index=True,
    )
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/pdf")
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # ------------------------------------------------------------------ #
    # Processing lifecycle (FR-005)                                        #
    # ------------------------------------------------------------------ #
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        index=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ------------------------------------------------------------------ #
    # Soft-delete                                                          #
    # ------------------------------------------------------------------ #
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # ------------------------------------------------------------------ #
    # Flexible metadata (document type, page count, etc.)                  #
    # ------------------------------------------------------------------ #
    doc_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSON, nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    owner: Mapped[User] = relationship("User", back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(
        "DocumentPage",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentPage.page_number",
    )
    sections: Mapped[list[DocumentSection]] = relationship(
        "DocumentSection",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_processable(self) -> bool:
        return self.status in {DocumentStatus.UPLOADED, DocumentStatus.FAILED}

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} filename={self.filename!r} status={self.status}>"


# ============================================================================
# DocumentPage
# ============================================================================


class DocumentPage(Base):
    """Raw text extracted from a single PDF page (FR-007, plan §3).

    Stored before chunking so text can be re-processed without re-parsing.
    """

    __tablename__ = "document_pages"

    __table_args__ = (
        # Efficient lookup by document + page number.
        Index("ix_pages_document_page", "document_id", "page_number"),
        UniqueConstraint("document_id", "page_number", name="uq_pages_document_page"),
    )

    # ------------------------------------------------------------------ #
    # Parent document                                                      #
    # ------------------------------------------------------------------ #
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Page content                                                         #
    # ------------------------------------------------------------------ #
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ocr: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True when text was obtained via OCR (FR-008)",
    )
    page_metadata: Mapped[Optional[dict]] = mapped_column("page_metadata", JSON, nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    document: Mapped[Document] = relationship("Document", back_populates="pages")
    sections: Mapped[list[DocumentSection]] = relationship(
        "DocumentSection",
        back_populates="page",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DocumentPage id={self.id} doc={self.document_id} page={self.page_number}>"


# ============================================================================
# DocumentSection
# ============================================================================


class DocumentSection(Base):
    """Structural section of a document — the *parent* retrieval unit.

    Corresponds to a heading / paragraph block extracted by the parser.
    Child chunks in ``DocumentChunk`` reference this row (FR-010, FR-016).

    Schema: plan.md §3 document_sections table.
    """

    __tablename__ = "document_sections"

    __table_args__ = (
        Index("ix_sections_document", "document_id"),
        Index("ix_sections_document_page", "document_id", "page_number"),
    )

    # ------------------------------------------------------------------ #
    # Parent references                                                    #
    # ------------------------------------------------------------------ #
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_pages.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ------------------------------------------------------------------ #
    # Section content                                                      #
    # ------------------------------------------------------------------ #
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heading: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True, index=True)
    section_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Character offsets within the full page / document text.
    start_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Section ordering within the document (0-based).
    section_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Flexible metadata (tables, figures, section depth, etc.)
    section_metadata: Mapped[Optional[dict]] = mapped_column(
        "section_metadata", JSON, nullable=True
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    document: Mapped[Document] = relationship("Document", back_populates="sections")
    page: Mapped[Optional[DocumentPage]] = relationship(
        "DocumentPage", back_populates="sections"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        back_populates="section",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentChunk.chunk_order",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DocumentSection id={self.id} doc={self.document_id} "
            f"page={self.page_number} heading={self.heading!r}>"
        )


# ============================================================================
# DocumentChunk
# ============================================================================


class DocumentChunk(Base):
    """Child retrieval chunk derived from a DocumentSection.

    Carries both the dense embedding vector (pgvector) and the raw chunk text
    for keyword/full-text search (FR-013, FR-014, FR-011).

    Schema: plan.md §3 document_chunks + embeddings tables merged.
    """

    __tablename__ = "document_chunks"

    __table_args__ = (
        # GIN index for full-text search will be added by migration (FR-014).
        # This declarative index covers metadata lookups.
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_section", "section_id"),
        Index("ix_chunks_document_page", "document_id", "page_number"),
    )

    # ------------------------------------------------------------------ #
    # Parent references                                                    #
    # ------------------------------------------------------------------ #
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Chunk content                                                        #
    # ------------------------------------------------------------------ #
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="0-based ordering of this chunk within its parent section",
    )

    # ------------------------------------------------------------------ #
    # Source metadata (FR-011)                                             #
    # ------------------------------------------------------------------ #
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heading: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    # filename is denormalised here so retrieval queries avoid a join.
    filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    document_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chunk_metadata: Mapped[Optional[dict]] = mapped_column(
        "chunk_metadata", JSON, nullable=True
    )

    # ------------------------------------------------------------------ #
    # Embedding (FR-012, FR-013)                                           #
    # ------------------------------------------------------------------ #
    # Dimension is intentionally left at 384 to match BAAI/bge-small-en-v1.5.
    # If the embedding model changes, a migration must ALTER this column.
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(384),
        nullable=True,
        comment="Dense embedding vector from the configured embedding model",
    )
    embedding_model: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
        comment="Identifier of the model used to generate this embedding",
    )

    # Token length of chunk_text (stored to avoid re-counting at query time).
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    document: Mapped[Document] = relationship("Document", back_populates="chunks")
    section: Mapped[Optional[DocumentSection]] = relationship(
        "DocumentSection", back_populates="chunks"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<DocumentChunk id={self.id} doc={self.document_id} "
            f"page={self.page_number} order={self.chunk_order}>"
        )


# ============================================================================
# Conversation
# ============================================================================


class Conversation(Base):
    """Chat session belonging to a User, optionally scoped to documents.

    Spec: FR-020 – FR-022, Key Entities — Conversation.
    Schema: plan.md §3 conversations table.
    """

    __tablename__ = "conversations"

    __table_args__ = (
        Index("ix_conversations_user", "user_id"),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    # ------------------------------------------------------------------ #
    # Ownership                                                            #
    # ------------------------------------------------------------------ #
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Session metadata                                                     #
    # ------------------------------------------------------------------ #
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # JSON list of document UUIDs that scope retrieval for this conversation
    # (FR-022). Stored as JSON so we avoid a many-to-many join table at this
    # stage; can be normalised later.
    document_scope: Mapped[Optional[list]] = mapped_column(
        "document_scope",
        JSON,
        nullable=True,
        comment="List of document UUIDs that scope retrieval for this conversation",
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    user: Mapped[User] = relationship("User", back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Conversation id={self.id} user={self.user_id} title={self.title!r}>"


# ============================================================================
# Message
# ============================================================================


class Message(Base):
    """Single turn within a Conversation.

    Stores both the original user text and the rewritten standalone query
    (FR-021) for auditability.

    Schema: plan.md §3 messages table.
    """

    __tablename__ = "messages"

    __table_args__ = (
        Index("ix_messages_conversation", "conversation_id"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    # ------------------------------------------------------------------ #
    # Parent conversation                                                  #
    # ------------------------------------------------------------------ #
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised for quick per-user history queries.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------ #
    # Message content                                                      #
    # ------------------------------------------------------------------ #
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="user | assistant | system",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # The query rewritten to be standalone for retrieval (FR-021).
    # NULL for assistant / system messages.
    standalone_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------ #
    # Answer metadata (citations, retrieval scores, etc.)                 #
    # ------------------------------------------------------------------ #
    message_metadata: Mapped[Optional[dict]] = mapped_column(
        "message_metadata",
        JSON,
        nullable=True,
        comment="Citations, retrieval chunk refs, scores, etc.",
    )

    # ------------------------------------------------------------------ #
    # Relationships                                                        #
    # ------------------------------------------------------------------ #
    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message id={self.id} role={self.role} conv={self.conversation_id}>"


# ============================================================================
# EvaluationCase
# ============================================================================


class EvaluationCase(Base):
    """Benchmark question used for retrieval and answer quality regression.

    Spec: FR-025, User Story 5.
    Schema: plan.md §3 evaluation_cases + evaluation_runs merged into one model
    (evaluation_runs will be a separate table once evaluation service is built).
    """

    __tablename__ = "evaluation_cases"

    # ------------------------------------------------------------------ #
    # Case definition                                                      #
    # ------------------------------------------------------------------ #
    name: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        index=True,
        comment="Human-readable identifier for this benchmark case",
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # JSON list of document UUIDs that scope retrieval for this case.
    document_scope: Mapped[Optional[list]] = mapped_column("document_scope", JSON, nullable=True)

    # Freeform tags for grouping / filtering cases (e.g. ["procurement", "p1"]).
    tags: Mapped[Optional[list]] = mapped_column("tags", JSON, nullable=True)

    # ------------------------------------------------------------------ #
    # Last run result (denormalised for quick dashboard queries)           #
    # ------------------------------------------------------------------ #
    last_status: Mapped[Optional[str]] = mapped_column(
        String(16),
        nullable=True,
        comment="PENDING | PASSED | FAILED | ERROR — outcome of the most recent run",
    )
    last_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_details: Mapped[Optional[dict]] = mapped_column(
        "last_run_details", JSON, nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EvaluationCase id={self.id} name={self.name!r}>"
