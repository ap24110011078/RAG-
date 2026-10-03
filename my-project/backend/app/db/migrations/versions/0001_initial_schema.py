"""Initial schema — all models for RAG Document Intelligence chatbot.

Revision ID: 0001_initial_schema
Revises: (none)
Create Date: 2026-09-07 00:00:00 UTC

Tables created
--------------
- users
- documents
- document_pages
- document_sections
- document_chunks         (includes pgvector VECTOR(384) column)
- conversations
- messages
- evaluation_cases

Extensions enabled
------------------
- vector   (pgvector — required before creating VECTOR columns)
- pg_trgm  (trigram — required for GIN keyword search on chunk text)

Indexes
-------
Standard BTree indexes are created by the ORM model declarations and
reflected here.  The following *additional* indexes are created
explicitly in this migration:

1. GIN trigram index on document_chunks.chunk_text  (FR-014 keyword search)
2. HNSW vector index on document_chunks.embedding   (FR-013 semantic search)
   - Dimension 384 matches BAAI/bge-small-en-v1.5 (spec §config.py default)
   - m=16, ef_construction=64 are safe defaults for a cold start; tune later.

Downgrade
---------
All tables are dropped in reverse dependency order.  The pgvector and
pg_trgm extensions are NOT dropped on downgrade to avoid removing them
from databases that may have other users.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision bookkeeping
# ---------------------------------------------------------------------------
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Embedding vector dimension — must match embedding_provider config.
# BAAI/bge-small-en-v1.5 produces 384-dimensional vectors.
EMBEDDING_DIM = 384


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 0. Enable PostgreSQL extensions                                       #
    # ------------------------------------------------------------------ #
    # CREATE EXTENSION IF NOT EXISTS is idempotent — safe to run repeatedly.
    # postgres-init.sql already runs these on first container start, but this
    # migration makes the dependency explicit so fresh migrations work too.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ------------------------------------------------------------------ #
    # 1. users                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ------------------------------------------------------------------ #
    # 2. documents                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_documents_owner_hash"),
    )
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"])
    op.create_index("ix_documents_owner_uploaded", "documents", ["owner_id", "uploaded_at"])
    op.create_index("ix_documents_status_deleted", "documents", ["status", "deleted_at"])

    # ------------------------------------------------------------------ #
    # 3. document_pages                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "document_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_text", sa.Text(), nullable=True),
        sa.Column("is_ocr", sa.Boolean(), nullable=False, comment="True when text was obtained via OCR (FR-008)"),
        sa.Column("page_metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "page_number", name="uq_pages_document_page"),
    )
    op.create_index("ix_document_pages_id", "document_pages", ["id"])
    op.create_index("ix_document_pages_document_id", "document_pages", ["document_id"])
    op.create_index("ix_pages_document_page", "document_pages", ["document_id", "page_number"])

    # ------------------------------------------------------------------ #
    # 4. document_sections                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "document_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("heading", sa.String(1024), nullable=True),
        sa.Column("section_text", sa.Text(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("section_metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["document_pages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_sections_id", "document_sections", ["id"])
    op.create_index("ix_document_sections_document_id", "document_sections", ["document_id"])
    op.create_index("ix_document_sections_heading", "document_sections", ["heading"])
    op.create_index("ix_sections_document", "document_sections", ["document_id"])
    op.create_index("ix_sections_document_page", "document_sections", ["document_id", "page_number"])

    # ------------------------------------------------------------------ #
    # 5. document_chunks                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("chunk_order", sa.Integer(), nullable=False, comment="0-based ordering of this chunk within its parent section"),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("heading", sa.String(1024), nullable=True),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("document_type", sa.String(64), nullable=True),
        sa.Column("chunk_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "embedding",
            sa.Text(),  # placeholder type — replaced by raw DDL below
            nullable=True,
            comment="Dense embedding vector from the configured embedding model",
        ),
        sa.Column("embedding_model", sa.String(128), nullable=True, comment="Identifier of the model used to generate this embedding"),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["document_sections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Replace the placeholder TEXT column with the real VECTOR(384) type.
    # We cannot pass pgvector's Vector() type through sa.Column in op.create_table
    # when the extension may not be loaded in the migration connection's type cache,
    # so we ALTER the column immediately after creation.
    op.execute(f"ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM}) USING NULL")

    op.create_index("ix_document_chunks_id", "document_chunks", ["id"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_section", "document_chunks", ["section_id"])
    op.create_index("ix_chunks_document_page", "document_chunks", ["document_id", "page_number"])

    # GIN trigram index for full-text / keyword search (FR-014, plan §search indexes).
    op.execute(
        "CREATE INDEX ix_chunks_chunk_text_trgm "
        "ON document_chunks USING GIN (chunk_text gin_trgm_ops)"
    )

    # HNSW vector index for approximate nearest-neighbour semantic search (FR-013).
    # Parameters: m=16 (connections per layer), ef_construction=64 (build-time beam width).
    # These are conservative defaults; tune based on dataset size and recall targets.
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        f"ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------ #
    # 6. conversations                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("document_scope", sa.JSON(), nullable=True, comment="List of document UUIDs that scope retrieval for this conversation"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_user", "conversations", ["user_id"])
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    # ------------------------------------------------------------------ #
    # 7. messages                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, comment="user | assistant | system"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("standalone_query", sa.Text(), nullable=True),
        sa.Column("message_metadata", sa.JSON(), nullable=True, comment="Citations, retrieval chunk refs, scores, etc."),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_conversation", "messages", ["conversation_id"])
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])

    # ------------------------------------------------------------------ #
    # 8. evaluation_cases                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "evaluation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=True),
        sa.Column("document_scope", sa.JSON(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("last_status", sa.String(16), nullable=True, comment="PENDING | PASSED | FAILED | ERROR — outcome of the most recent run"),
        sa.Column("last_score", sa.Float(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_details", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_cases_id", "evaluation_cases", ["id"])
    op.create_index("ix_evaluation_cases_name", "evaluation_cases", ["name"])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # Drop tables in reverse dependency order (children before parents).
    op.drop_table("evaluation_cases")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("document_chunks")
    op.drop_table("document_sections")
    op.drop_table("document_pages")
    op.drop_table("documents")
    op.drop_table("users")
    # NOTE: pgvector and pg_trgm extensions are intentionally NOT dropped on
    # downgrade — they may be shared by other databases on the same server.
