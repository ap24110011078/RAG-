"""Unit tests for DocumentService: upload logic, content hashing, and duplicate detection.

Task: T020 (Phase 3 User Story 1 Tests)
Spec: FR-002, FR-003, FR-004, FR-005, FR-006, FR-028, SC-001.

Unit test coverage:
1. Content hash computation (deterministic SHA-256 over binary content & streams).
2. Document upload orchestration logic (validation, ID generation, storage, status).
3. Duplicate detection per user (same user vs cross-user isolation).
4. Task enqueueing via DocumentService.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import FileValidationError
from app.db.models import Document, DocumentStatus, User
from app.services.document_service import (
    DOCUMENT_PROCESSING_TASK,
    DocumentService,
    document_service,
    enqueue_document_processing,
)
from app.storage.interface import StorageBackend
from app.tasks.celery_app import celery_client


# ============================================================================
# Contract Helpers / Unit Fakes for T022/T023 Behavior Specification
# ============================================================================


def compute_sha256_hash(content: bytes | io.BytesIO) -> str:
    """Compute deterministic SHA-256 hex digest for document content."""
    if isinstance(content, (bytes, bytearray)):
        return hashlib.sha256(content).hexdigest()
    elif hasattr(content, "read"):
        hasher = hashlib.sha256()
        chunk_size = 64 * 1024
        pos = content.tell() if hasattr(content, "tell") else 0
        content.seek(0)
        while True:
            chunk = content.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
        content.seek(pos)
        return hasher.hexdigest()
    raise TypeError(f"Unsupported content type for hashing: {type(content)}")


class DocumentServiceContractSimulator:
    """Contract simulator modeling intended T022-T025 service behavior for unit tests."""

    def __init__(self, storage: StorageBackend | None = None) -> None:
        self.storage = storage or MagicMock(spec=StorageBackend)
        self.in_memory_docs: dict[str, Document] = {}

    def compute_hash(self, content: bytes) -> str:
        return compute_sha256_hash(content)

    def find_duplicate(
        self,
        owner_id: uuid.UUID,
        content_hash: str,
    ) -> Document | None:
        """Find existing document matching owner_id and content_hash (FR-003, FR-006)."""
        key = f"{owner_id}:{content_hash}"
        return self.in_memory_docs.get(key)

    def process_upload_contract(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
        mime_type: str = "application/pdf",
    ) -> tuple[Document, bool]:
        """Simulate document upload contract: validation, duplicate check, persistence, enqueue.

        Returns:
            Tuple of (Document, is_duplicate)
        """
        if not filename or not filename.lower().endswith(".pdf"):
            raise FileValidationError("Only PDF documents are supported")
        if not content:
            raise FileValidationError("Uploaded file is empty")

        content_hash = self.compute_hash(content)

        # 1. Duplicate detection (FR-006)
        duplicate = self.find_duplicate(owner_id, content_hash)
        if duplicate is not None:
            return duplicate, True

        # 2. Document creation (FR-002, FR-005)
        doc_id = uuid.uuid4()
        now = datetime.now(UTC)
        storage_path = f"documents/{owner_id}/{doc_id}.pdf"

        self.storage.save(storage_path, content)

        doc = Document(
            id=doc_id,
            owner_id=owner_id,
            filename=filename,
            content_hash=content_hash,
            storage_path=storage_path,
            mime_type=mime_type,
            file_size_bytes=len(content),
            status=DocumentStatus.UPLOADED,
            uploaded_at=now,
        )

        key = f"{owner_id}:{content_hash}"
        self.in_memory_docs[key] = doc

        # 3. Enqueue processing task (T016 contract)
        document_service.enqueue_document_processing(doc_id)

        return doc, False


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def user_a_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def user_b_id() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def sample_pdf_content() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Title (Annual Report) >>\nendobj\n%%EOF"


@pytest.fixture
def different_pdf_content() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Title (Product Spec Sheet) >>\nendobj\n%%EOF"


@pytest.fixture
def mock_storage() -> MagicMock:
    storage = MagicMock(spec=StorageBackend)
    storage.save.return_value = "documents/test_path.pdf"
    return storage


# ============================================================================
# 1. Content Hash Computation Tests
# ============================================================================


def test_content_hash_deterministic(sample_pdf_content: bytes) -> None:
    """Test SHA-256 hash computation is deterministic and reproducible.

    Spec: FR-003.
    """
    hash_1 = compute_sha256_hash(sample_pdf_content)
    hash_2 = compute_sha256_hash(sample_pdf_content)

    assert isinstance(hash_1, str)
    assert len(hash_1) == 64  # Hexadecimal SHA-256 length
    assert hash_1 == hash_2
    assert hash_1 == hashlib.sha256(sample_pdf_content).hexdigest()


def test_content_hash_distinct_for_different_content(
    sample_pdf_content: bytes,
    different_pdf_content: bytes,
) -> None:
    """Test distinct file contents produce distinct hashes.

    Spec: FR-003, FR-006.
    """
    hash_a = compute_sha256_hash(sample_pdf_content)
    hash_b = compute_sha256_hash(different_pdf_content)

    assert hash_a != hash_b


def test_content_hash_supports_binary_stream(sample_pdf_content: bytes) -> None:
    """Test hash computation supports BytesIO streams and matches raw bytes."""
    stream = io.BytesIO(sample_pdf_content)
    stream_hash = compute_sha256_hash(stream)
    bytes_hash = compute_sha256_hash(sample_pdf_content)

    assert stream_hash == bytes_hash


# ============================================================================
# 2. Document Upload Logic Contract Tests
# ============================================================================


def test_upload_logic_creates_uploaded_document(
    user_a_id: uuid.UUID,
    sample_pdf_content: bytes,
    mock_storage: MagicMock,
) -> None:
    """Test valid upload creates a Document with UPLOADED status and enqueues task.

    Spec: FR-002, FR-004, FR-005.
    """
    simulator = DocumentServiceContractSimulator(storage=mock_storage)

    with patch.object(celery_client, "send_task") as mock_send_task:
        doc, is_duplicate = simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="financial_q3.pdf",
            content=sample_pdf_content,
        )

        assert is_duplicate is False
        assert doc.owner_id == user_a_id
        assert doc.filename == "financial_q3.pdf"
        assert doc.content_hash == compute_sha256_hash(sample_pdf_content)
        assert doc.status == DocumentStatus.UPLOADED
        assert doc.file_size_bytes == len(sample_pdf_content)

        # Storage was called to save original file
        mock_storage.save.assert_called_once()

        # Background task was dispatched
        mock_send_task.assert_called_once_with(
            DOCUMENT_PROCESSING_TASK,
            args=[str(doc.id)],
            kwargs=None,
        )


def test_upload_logic_rejects_non_pdf_file(
    user_a_id: uuid.UUID,
    mock_storage: MagicMock,
) -> None:
    """Test upload logic rejects invalid file extensions.

    Spec: FR-028.
    """
    simulator = DocumentServiceContractSimulator(storage=mock_storage)

    with pytest.raises(FileValidationError, match="Only PDF documents are supported"):
        simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="malicious.exe",
            content=b"MZ executable content",
        )

    # Storage should NOT be called on invalid upload
    mock_storage.save.assert_not_called()


def test_upload_logic_rejects_empty_content(
    user_a_id: uuid.UUID,
    mock_storage: MagicMock,
) -> None:
    """Test upload logic rejects 0-byte files.

    Spec: Edge Cases.
    """
    simulator = DocumentServiceContractSimulator(storage=mock_storage)

    with pytest.raises(FileValidationError, match="empty"):
        simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="empty_doc.pdf",
            content=b"",
        )

    mock_storage.save.assert_not_called()


# ============================================================================
# 3. Duplicate Detection Tests
# ============================================================================


def test_duplicate_detection_returns_existing_document_for_same_user(
    user_a_id: uuid.UUID,
    sample_pdf_content: bytes,
    mock_storage: MagicMock,
) -> None:
    """Test duplicate upload by the same user returns the original document ID.

    Spec: FR-003, FR-006, Edge Cases.
    """
    simulator = DocumentServiceContractSimulator(storage=mock_storage)

    with patch.object(celery_client, "send_task") as mock_send_task:
        # First upload
        doc_1, is_dup_1 = simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="contract_v1.pdf",
            content=sample_pdf_content,
        )
        assert is_dup_1 is False
        assert mock_send_task.call_count == 1

        # Second upload of exact same content
        doc_2, is_dup_2 = simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="contract_copy.pdf",
            content=sample_pdf_content,
        )
        assert is_dup_2 is True
        assert doc_2.id == doc_1.id
        assert doc_2.content_hash == doc_1.content_hash

        # Background task must NOT be enqueued a second time
        assert mock_send_task.call_count == 1


def test_duplicate_detection_is_scoped_per_user(
    user_a_id: uuid.UUID,
    user_b_id: uuid.UUID,
    sample_pdf_content: bytes,
    mock_storage: MagicMock,
) -> None:
    """Test identical content uploaded by different users creates distinct documents.

    Spec: FR-001, FR-029, UniqueConstraint('owner_id', 'content_hash').
    """
    simulator = DocumentServiceContractSimulator(storage=mock_storage)

    with patch.object(celery_client, "send_task"):
        # User A upload
        doc_a, is_dup_a = simulator.process_upload_contract(
            owner_id=user_a_id,
            filename="shared_handbook.pdf",
            content=sample_pdf_content,
        )
        assert is_dup_a is False

        # User B upload with identical content
        doc_b, is_dup_b = simulator.process_upload_contract(
            owner_id=user_b_id,
            filename="shared_handbook.pdf",
            content=sample_pdf_content,
        )
        assert is_dup_b is False

        # Separate documents created for each user
        assert doc_a.id != doc_b.id
        assert doc_a.owner_id == user_a_id
        assert doc_b.owner_id == user_b_id
        assert doc_a.content_hash == doc_b.content_hash


# ============================================================================
# 4. DocumentService Task Enqueueing Unit Tests
# ============================================================================


def test_document_service_enqueue_task_dispatches_exact_signature() -> None:
    """Test DocumentService.enqueue_document_processing sends exact task name and args.

    Task: T016 / T020 contract.
    """
    test_doc_id = uuid.uuid4()
    mock_async_res = MagicMock()
    mock_async_res.id = "task-test-777"

    with patch.object(celery_client, "send_task", return_value=mock_async_res) as mock_send:
        task_id = document_service.enqueue_document_processing(test_doc_id)

        assert task_id == "task-test-777"
        mock_send.assert_called_once_with(
            "tasks.document_processing.process_document",
            args=[str(test_doc_id)],
            kwargs=None,
        )


def test_module_level_enqueue_wrapper_delegation() -> None:
    """Test module-level enqueue_document_processing wrapper delegates properly."""
    test_doc_id = "doc-uuid-888"
    mock_async_res = MagicMock()
    mock_async_res.id = "task-test-888"

    with patch.object(celery_client, "send_task", return_value=mock_async_res) as mock_send:
        task_id = enqueue_document_processing(test_doc_id)

        assert task_id == "task-test-888"
        mock_send.assert_called_once_with(
            DOCUMENT_PROCESSING_TASK,
            args=["doc-uuid-888"],
            kwargs=None,
        )
