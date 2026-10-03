# Tasks: Enterprise Document Intelligence Chatbot

**Input**: spec.md, plan.md

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the repository and foundational service scaffolding.

- [P] T001 Create `backend/`, `frontend/`, `worker/`, and `infra/` directories with initial README notes.
- [P] T002 Initialize `backend/pyproject.toml` with FastAPI, Pydantic v2, SQLAlchemy 2.x, asyncpg, Celery, Redis, PyMuPDF, python-docx, python-pptx, Tesseract, pgvector support, and test dependencies.
- [P] T003 Initialize `frontend/` with Vite, React, TypeScript, Tailwind CSS, and basic application scaffolding.
- [P] T004 Create `infra/docker-compose.yml`, `infra/Dockerfile.backend`, `infra/Dockerfile.frontend`, `infra/Dockerfile.worker`, and `infra/.env.example`.
- [P] T005 Add shared environment configuration handling in `backend/app/core/config.py` and `worker/celery_worker.py`.
- [P] T006 Add structured logging setup in `backend/app/core/logging.py` and configure a JSON-friendly logger.
- [P] T007 Add backend health endpoints in `backend/app/api/health.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Implement the core backend infrastructure required by all later user stories.

- [ ] T008 Define database models in `backend/app/db/models.py` for `User`, `Document`, `DocumentPage`, `DocumentSection`, `DocumentChunk`, `Conversation`, `Message`, and `EvaluationCase`.
- [ ] T009 Configure SQLAlchemy async session management in `backend/app/db/session.py` and repository wiring in `backend/app/db/repositories.py`.
- [ ] T010 Create database migration setup under `backend/app/db/migrations/` and initial migration for the schema.
- [ ] T011 Implement JWT authentication and secure password hashing in `backend/app/services/auth_service.py` and `backend/app/core/security.py`.
- [ ] T012 Add auth router in `backend/app/api/auth.py` with `/register`, `/login`, and `/me` endpoints.
- [ ] T013 Add request validation and error handling utilities in `backend/app/core/exceptions.py` and `backend/app/core/dependencies.py`.
- [ ] T014 Implement storage abstraction interface in `backend/app/storage/interface.py` and local filesystem backend in `backend/app/storage/local_storage.py`.
- [ ] T015 Add Celery application bootstrap in `worker/celery_worker.py` and configure Redis broker/backend.
- [ ] T016 Create document processing task skeleton in `worker/tasks/document_processing.py` and wire task invocation from `backend/app/services/document_service.py`.
- [ ] T017 Add `backend/app/core/metrics.py` for request timing and basic worker metrics.
- [ ] T018 Implement authorization dependencies in `backend/app/core/dependencies.py` so endpoints enforce user ownership boundaries.

---

## Phase 3: User Story 1 - Secure Document Upload and Background Ingestion (Priority: P1)

**Goal**: Enable authenticated users to upload PDF documents, immediately receive an upload response, and process documents asynchronously.

**Independent Test**: Upload a PDF as an authenticated user and verify the document appears with `UPLOADED` status and a background task is queued.

### Tests
- [P] T019 Create API tests in `backend/tests/api/test_documents_upload.py` for PDF upload, duplicate detection, and invalid file rejection.
- [P] T020 Create unit tests in `backend/tests/unit/test_document_service.py` for upload logic, hash computation, and duplicate detection.

### Implementation
- [ ] T021 Implement `POST /api/documents/upload` in `backend/app/api/documents.py`.
- [ ] T022 Implement document model persistence and content hash storage in `backend/app/services/document_service.py`.
- [ ] T023 Implement duplicate detection and immediate response behavior in `backend/app/services/document_service.py`.
- [ ] T024 Implement storage of original PDF files in `backend/app/storage/local_storage.py`.
- [ ] T025 Implement document status tracking in `backend/app/db/models.py` and `backend/app/services/document_service.py`.
- [ ] T026 Add `GET /api/documents` and `GET /api/documents/{id}` endpoints in `backend/app/api/documents.py`.
- [ ] T027 Add `GET /api/documents/{id}/status` endpoint in `backend/app/api/documents.py`.
- [ ] T028 Add `DELETE /api/documents/{id}` endpoint in `backend/app/api/documents.py` and service logic to remove document from retrieval.
- [ ] T029 Implement background task enqueueing for document processing in `backend/app/services/document_service.py`.
- [ ] T030 Implement the document upload form and document management UI in `frontend/src/pages/DocumentsPage.tsx` and `frontend/src/components/documents/DocumentUploadForm.tsx`.
- [ ] T031 Add document list and status display in `frontend/src/pages/DocumentsPage.tsx` and `frontend/src/components/documents/DocumentList.tsx`.

---

## Phase 4: User Story 2 - Document Parsing, Chunking, and Embeddings (Priority: P1)

**Goal**: Parse uploaded PDFs, preserve structure, create parent-child chunks, and persist embeddings.

**Independent Test**: Process an uploaded PDF in the background and confirm chunks and embeddings are stored correctly.

### Tests
- [P] T032 Add unit tests in `backend/tests/unit/test_parser.py` for PyMuPDF extraction, page numbers, and structure preservation.
- [P] T033 Add unit tests in `backend/tests/unit/test_chunking.py` for parent-child chunk formation and metadata assignment.
- [P] T034 Add integration tests in `backend/tests/integration/test_document_processing.py` for end-to-end ingestion and persistence.

### Implementation
- [ ] T035 Implement PDF parsing in `backend/app/rag/parser.py` using PyMuPDF and OCR abstraction for scanned documents.
- [ ] T036 Implement text normalization in `backend/app/rag/text_normalizer.py`.
- [ ] T037 Implement parent section extraction and child chunk creation in `backend/app/rag/parser.py` or `backend/app/rag/chunker.py`.
- [ ] T038 Implement metadata enrichment in chunk creation with document ID, filename, page number, heading, section, and document type.
- [ ] T039 Implement embedding provider abstraction in `backend/app/rag/embedding_provider.py`.
- [ ] T040 Implement initial BAAI/bge-small-en-v1.5 embedding flow in `backend/app/rag/embedding_provider.py`.
- [ ] T041 Persist chunk embeddings and metadata in `backend/app/db/models.py` or a dedicated embeddings table.
- [ ] T042 Extend document processing task in `worker/tasks/document_processing.py` to run parsing, chunking, embedding, and persistence.
- [ ] T043 Implement OCR abstraction in `backend/app/rag/ocr.py` with Tesseract support.
- [ ] T044 Add processing state updates and failure handling to `worker/tasks/document_processing.py`.

---

## Phase 5: User Story 3 - Hybrid Retrieval and Grounded Q&A (Priority: P1)

**Goal**: Enable retrieval of relevant document evidence and generation of grounded answers with citations.

**Independent Test**: Ask a question over ingested documents and verify the answer includes citations and does not hallucinate when evidence is missing.

### Tests
- [P] T045 Add unit tests in `backend/tests/unit/test_retriever.py` for semantic retrieval, keyword retrieval, and metadata filtering.
- [P] T046 Add unit tests in `backend/tests/unit/test_ranker.py` for Reciprocal Rank Fusion.
- [P] T047 Add API tests in `backend/tests/api/test_chat.py` for query and answer generation flows.

### Implementation
- [ ] T048 Implement `backend/app/rag/retriever.py` for semantic vector search and keyword search.
- [ ] T049 Implement `backend/app/rag/hybrid_ranker.py` for Reciprocal Rank Fusion.
- [ ] T050 Implement `backend/app/rag/prompt_builder.py` and `backend/app/rag/citation_builder.py`.
- [ ] T051 Implement `backend/app/rag/llm_provider.py` with provider abstraction and Gemini API support.
- [ ] T052 Implement `POST /api/chat/query` and `POST /api/conversations/{id}/messages` in `backend/app/api/chat.py` and `backend/app/api/conversations.py`.
- [ ] T053 Implement conversation history persistence and standalone query rewriting in `backend/app/services/conversation_service.py`.
- [ ] T054 Implement LLM generation pipeline in `backend/app/services/retrieval_service.py` or `backend/app/services/chat_service.py`.
- [ ] T055 Implement prompt grounding and evidence injection in the chat flow.
- [ ] T056 Add chat UI and citation rendering in `frontend/src/pages/ChatPage.tsx` and `frontend/src/components/chat/ChatWindow.tsx`.
- [ ] T057 Add conversation list and selection UI in `frontend/src/pages/DashboardPage.tsx` or `frontend/src/components/chat/ConversationList.tsx`.

---

## Phase 6: User Story 4 - Document Management, Authorization, and Conversation Scope (Priority: P2)

**Goal**: Ensure users can manage documents, delete them safely, and maintain document-scoped conversations with authorization.

**Independent Test**: Delete a document and confirm it is excluded from retrieval and conversation scope for that user.

### Tests
- [P] T058 Add API tests in `backend/tests/api/test_documents_management.py` for list, delete, and status access control.
- [P] T059 Add unit tests in `backend/tests/unit/test_authorization.py` for document and conversation authorization rules.
- [P] T060 Add integration tests in `backend/tests/integration/test_document_deletion.py`.

### Implementation
- [ ] T061 Implement `POST /api/documents/{id}/retry` to requeue failed documents.
- [ ] T062 Implement document-scope metadata and conversation scoping in `backend/app/db/models.py` and chat query logic.
- [ ] T063 Implement authorization enforcement across `documents`, `conversations`, and `chat` APIs.
- [ ] T064 Implement frontend document delete flows in `frontend/src/components/documents/DocumentList.tsx`.
- [ ] T065 Implement frontend conversation scope controls in `frontend/src/pages/ChatPage.tsx`.

---

## Phase 7: User Story 5 - Evaluation and Reliability (Priority: P3)

**Goal**: Add evaluation tooling and reliability tracking for document processing and retrieval quality.

**Independent Test**: Run evaluation cases and verify quality metrics are produced.

### Tests
- [P] T066 Add evaluation tests in `backend/tests/evaluation/test_evaluation.py`.
- [P] T067 Add integration tests in `backend/tests/integration/test_evaluation_pipeline.py`.

### Implementation
- [ ] T068 Implement `backend/app/services/evaluation_service.py` and `worker/tasks/run_evaluation.py`.
- [ ] T069 Add evaluation dataset fixtures under `backend/tests/fixtures/`.
- [ ] T070 Implement retrieval and answer quality metrics storage in `backend/app/db/models.py` or evaluation tables.
- [ ] T071 Add health/readiness enhancements in `backend/app/api/health.py`.
- [ ] T072 Add processing failure tracking and error metadata in `backend/app/services/document_service.py`.
- [ ] T073 Add backend telemetry or metrics logging for document processing durations, retrieval latency, and task failures.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Hardening, documentation, and final production readiness.

- [P] T074 Add security hardening in `backend/app/core/security.py` and validate all API inputs.
- [P] T075 Add `.env.example` documentation in `infra/.env.example` and backend environment variable docs.
- [P] T076 Add Docker Compose override for production and local development in `infra/docker-compose.yml`.
- [P] T077 Add API docs and README sections describing auth, document ingestion, chat, and evaluation.
- [P] T078 Add end-to-end or smoke tests to validate the full upload-to-answer flow.
- [P] T079 Add code cleanup, type checking, and formatting enforcement for backend and frontend.
- [P] T080 Add observability documentation and runtime guidance for logs, health checks, and failure handling.

---

## Dependencies & Execution Order

### Phase Dependencies
- **Setup**: must complete before the foundation work begins.
- **Foundational**: blocks all user stories until auth, DB, storage, Celery, and core routing are in place.
- **User Stories**: begin after Foundational completion; User Story 1 and 2 should be prioritized in parallel.
- **Polish**: begins after core functionality is implemented and tested.

### User Story Dependencies
- US1 depends on Phase 2 foundational infrastructure.
- US2 depends on US1 document ingestion and Phase 2 retrieval/embedding wiring.
- US3 depends on US1/US2 and authorization enforcement.
- US4 depends on US2 retrieval and conversation models.
- US5 depends on US1/US2/US3 and evaluation dataset availability.

### Parallel Opportunities
- Setup tasks marked `[P]` can run in parallel by different team members.
- Foundational tasks marked `[P]` can also run concurrently.
- Document upload and ingestion tasks can overlap with frontend UI scaffolding once APIs are defined.
- Retrieval, LLM provider, and conversation modeling can proceed in parallel after core storage and auth are ready.
