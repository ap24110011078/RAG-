# Implementation Plan: Enterprise Document Intelligence Chatbot

**Branch**: `rag-document-intelligence` | **Date**: 2026-08-11 | **Spec**: `spec.md`

**Input**: Feature specification from `/spec.md`

## 1. Overall Architecture

This system is a modular, production-oriented SaaS-style web application with three primary service layers:

- Frontend: React + TypeScript + Vite + Tailwind CSS for a responsive web UI.
- Backend API: Python + FastAPI + Pydantic v2 + SQLAlchemy 2.x for REST APIs, auth, and orchestration.
- Background Worker: Celery + Redis for asynchronous document processing, ingestion, and evaluation.

The data layer is PostgreSQL with pgvector. Document storage is abstracted behind a storage interface; local filesystem storage is used initially and the interface supports future S3-compatible or cloud blob storage.

Core pipelines:
- Document ingestion and parsing
- Parent-child chunking and metadata enrichment
- Embedding generation and vector persistence
- Hybrid retrieval with semantic + keyword search
- Grounded LLM answer generation with citations
- PostgreSQL-backed conversation history and follow-up rewriting

## 2. Repository / Project Structure

```text
backend/
├── app/
│   ├── api/
│   │   ├── auth.py
│   │   ├── documents.py
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── health.py
│   │   └── processing.py
│   ├── core/
│   │   ├── config.py
│   │   ├── logging.py
│   │   ├── security.py
│   │   ├── dependencies.py
│   │   ├── exceptions.py
│   │   └── metrics.py
│   ├── db/
│   │   ├── base.py
│   │   ├── models.py
│   │   ├── repositories.py
│   │   ├── session.py
│   │   ├── schemas.py
│   │   └── migrations/
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── document_service.py
│   │   ├── processing_service.py
│   │   ├── retrieval_service.py
│   │   ├── conversation_service.py
│   │   ├── evaluation_service.py
│   │   └── security_service.py
│   ├── storage/
│   │   ├── interface.py
│   │   ├── local_storage.py
│   │   └── s3_storage.py
│   ├── tasks/
│   │   ├── celery_app.py
│   │   ├── document_tasks.py
│   │   ├── evaluation_tasks.py
│   │   └── retry.py
│   └── rag/
│       ├── embedding_provider.py
│       ├── llm_provider.py
│       ├── retriever.py
│       ├── hybrid_ranker.py
│       ├── prompt_builder.py
│       ├── citation_builder.py
│       ├── parser.py
│       └── text_normalizer.py
├── app.py
├── pyproject.toml
└── tests/
    ├── api/
    ├── unit/
    ├── integration/
    └── evaluation/

frontend/
├── public/
├── src/
│   ├── components/
│   │   ├── auth/
│   │   ├── chat/
│   │   ├── documents/
│   │   ├── layout/
│   │   └── ui/
│   ├── pages/
│   │   ├── LoginPage.tsx
│   │   ├── DashboardPage.tsx
│   │   ├── DocumentsPage.tsx
│   │   └── ChatPage.tsx
│   ├── services/
│   │   ├── api.ts
│   │   ├── auth.ts
│   │   ├── documents.ts
│   │   └── chat.ts
│   ├── stores/
│   ├── types/
│   ├── utils/
│   └── styles/
├── tests/
└── vite.config.ts

worker/
├── celery_worker.py
└── tasks/
    ├── process_document.py
    └── run_evaluation.py

infra/
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
├── Dockerfile.worker
├── .env.example
└── postgres-init.sql

tests/
├── integration/
└── evaluation/
```

### Structure Decision
A separate service layout is chosen to preserve modularity, enable independent deployment, and simplify scaling. The backend owns API, data, security, and orchestration. The worker handles document ingestion and long-running RAG tasks. The frontend is a single-page app consuming backend APIs.

## 3. Database Schema

### Core entities

- **users**
  - id, email, password_hash, created_at, updated_at, is_active

- **documents**
  - id, owner_id, filename, content_hash, storage_path, mime_type,
    status (UPLOADED, PROCESSING, APPROVED, FAILED), error_message,
    uploaded_at, processed_at, metadata JSON

- **document_pages**
  - id, document_id, page_number, page_text, page_metadata JSON

- **document_sections**
  - id, document_id, page_number, heading, section_text,
    start_offset, end_offset, metadata JSON

- **document_chunks**
  - id, section_id, document_id, page_number, chunk_text,
    chunk_order, parent_section_id, metadata JSON,
    embedding VECTOR, embedding_model, created_at

- **embeddings**
  - may be normalized into `document_chunks` or kept separate for vector storage compatibility; include model_name, vector, and chunk reference

- **conversations**
  - id, user_id, title, document_scope JSON, created_at, updated_at

- **messages**
  - id, conversation_id, user_id, role (user/system/assistant), text,
    standalone_query, created_at, metadata JSON

- **retrieval_results**
  - id, message_id, chunk_id, score, rank, source_type, metadata JSON

- **evaluation_cases**
  - id, name, document_scope JSON, query, expected_answer, tags, created_at

- **evaluation_runs**
  - id, case_id, status, score, details JSON, run_at

### Search indexes

- `pgvector` index on `document_chunks.embedding`
- GIN/GIN_TRGM or full-text search on `document_chunks.chunk_text` and document section text
- metadata indexes on `document_chunks.metadata -> document_id`, `document_id`, `page_number`, `heading`
- unique index on `documents.content_hash`

## 4. API Architecture

### Router layout
- `api/auth.py` → signup, login, refresh token, revoke session
- `api/documents.py` → upload, list, detail, delete, status, download original
- `api/processing.py` → processing status, retry failed document
- `api/chat.py` → send question, get answer, stream responses, rewrite follow-up
- `api/conversations.py` → create/list/update conversation, get history, document-scoped chat
- `api/health.py` → liveness, readiness, metrics

### API patterns
- Use dependency injection for auth and user context.
- Validate payloads with Pydantic v2 models.
- Use service layer patterns so routers call `document_service`, `retrieval_service`, etc.
- Keep controllers thin and business logic in services.
- Return typed response models and consistent error response schemas.

### Key endpoints
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/documents/upload`
- `GET /api/documents`
- `GET /api/documents/{id}`
- `DELETE /api/documents/{id}`
- `GET /api/documents/{id}/status`
- `POST /api/documents/{id}/retry`
- `POST /api/conversations`
- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `POST /api/conversations/{id}/messages`
- `GET /api/conversations/{id}/messages`
- `POST /api/chat/query`
- `GET /api/health/live`
- `GET /api/health/ready`

## 5. Document Ingestion Pipeline

1. **Upload request**
   - User uploads PDF to `POST /api/documents/upload`.
   - Validate MIME type and file size; reject unsupported or invalid files.
   - Compute content hash and detect duplicates immediately.
   - Store file via storage abstraction; return `document_id` and status `UPLOADED`.
   - Enqueue a Celery task for parsing and ingestion.

2. **Background processing**
   - Celery worker marks document status `PROCESSING`.
   - Load file from storage and parse with PyMuPDF.
   - Extract text by page, headings, tables, paragraphs, page numbers.
   - Store page-level structure in `document_pages` and `document_sections`.
   - Use OCR abstraction for scanned or image-heavy PDFs; initial implementation uses Tesseract.

3. **Normalization**
   - Clean whitespace, punctuation, unicode normalization, line breaks, encoding artifacts.
   - Normalize section headings and segment boundaries.

4. **Chunking**
   - Build parent sections from document structure and headings.
   - Create child chunks from parent sections with configurable max token/text length.
   - Associate child chunks to parent `section_id` and document metadata.

5. **Metadata enrichment**
   - Attach `document_id`, `filename`, `page_number`, `heading`, `section_title`, `document_type`, `uploaded_at`, and other metadata.

6. **Embedding generation**
   - Send child chunk text to embedding provider abstraction using BAAI/bge-small-en-v1.5 initially.
   - Persist embeddings alongside chunk records.

7. **Persistence**
   - Write chunk metadata, embeddings, and parsed structure to PostgreSQL.
   - Update document status to `APPROVED` or `FAILED` with error details.

8. **Duplicate prevention**
   - Use a content hash to skip duplicate ingestion.
   - Track processing state atomically so retries do not duplicate chunks.

## 6. RAG Retrieval Pipeline

### Retrieval architecture
- Hybrid retrieval service combines vector search, full-text keyword search, and metadata filtering.
- The service uses a query-time pipeline that returns ranked parent sections.

### Retrieval steps
1. **Query normalization**
   - Clean user query text; apply metadata scoping and document-scoped filters.

2. **Semantic retrieval**
   - Generate query embedding via the embedding provider.
   - Run pgvector similarity search against child chunk embeddings.

3. **Keyword retrieval**
   - Run PostgreSQL full-text search or trigram search across chunk text and section text.

4. **Metadata filtering**
   - Apply document ID, owner, page, heading, and conversation-scoped filters.

5. **Reciprocal Rank Fusion**
   - Combine semantic and keyword result rankings using RRF or equivalent fusion algorithm.
   - Score candidate chunks and select top parent sections.

6. **Parent-context reconstruction**
   - Promote highest-ranked parent sections and include associated child chunks for context.
   - Build a concise evidence set with citations.

7. **Evidence package**
   - Provide LLM with retrieved text, document identifiers, page numbers, and section labels.
   - Limit total context size based on token limits and configured thresholds.

## 7. LLM Generation Pipeline

### Provider abstraction
- Implement `llm_provider.py` with a provider interface.
- Initial provider: Gemini API.
- Support OpenAI-compatible and Ollama providers through the same interface.
- Load API keys and endpoints from environment variables only.

### Prompt workflow
- Create prompt templates for grounded answer generation.
- Include instructions to rely only on supplied evidence and cite sources.
- Add explicit fallback language for missing evidence: "I could not find an answer in the provided documents."

### Generation flow
1. **Prepare evidence**
   - Use top-ranked parent sections and associated chunk text.
   - Serialize citations clearly in the prompt.

2. **Build user query**
   - If the input is a follow-up, use rewrite service to produce a standalone retrieval query.

3. **Send to LLM**
   - Call provider with prompt, evidence, and optional system instructions.
   - Request structured output when possible: answer text + citation list.

4. **Post-process answer**
   - Validate the response; ensure no exposed secrets, no hallucination language if evidence is missing.
   - Store answer and citations in message history.

## 8. Conversation Architecture

### Conversation model
- Conversations belong to a user and may include a document scope.
- Messages store original user text, role, generated standalone query, and metadata.

### Follow-up handling
- When a user submits a message, the chat service may rewrite follow-up questions into standalone queries before retrieval.
- Use conversation history and document scope to contextualize the rewrite.
- Save both original and rewritten query for auditability.

### Context limits
- Limit context sent to the LLM by token budget.
- Prioritize evidence from the current document scope and recent conversation turns.
- Avoid sending the entire conversation history; use a summary or last relevant turns when needed.

### Conversation endpoints
- `POST /api/conversations` to create a new conversation.
- `GET /api/conversations` to list user conversations.
- `GET /api/conversations/{id}/messages` to fetch history.
- `POST /api/conversations/{id}/messages` to add a new message and answer query.

## 9. Background Worker Architecture

### Celery architecture
- `worker/celery_worker.py` instantiates the Celery app and configures Redis broker and result backend.
- Tasks live in `worker/tasks/document_processing.py` and `worker/tasks/evaluation.py`.
- Document ingestion tasks orchestrate parsing, chunking, embedding, and persistence.
- Retry logic handles transient failures and records failure metadata.

### Failures and reprocessing
- Document status transitions: UPLOADED → PROCESSING → APPROVED or FAILED.
- Store failure reasons and stack traces in `documents.error_message` or a separate audit table.
- Provide `POST /api/documents/{id}/retry` to requeue failed documents.
- Ensure idempotent processing: do not duplicate chunks on retry.

### Worker integration
- The backend enqueue task after upload and optionally after document updates.
- The worker reads from shared PostgreSQL and storage abstraction; all task payloads use document ID and stable metadata.

## 10. Frontend Architecture

### UI structure
- `LoginPage` and auth flows for JWT-based login.
- `DashboardPage` for user summary and recent conversations.
- `DocumentsPage` for upload, list, status, and deletion.
- `ChatPage` for document-scoped chat and answer display.

### Client services
- `api.ts` for HTTP client setup, token injection, and error handling.
- `auth.ts` for login, logout, token refresh, and user profile.
- `documents.ts` for upload form, status polling, and delete operations.
- `chat.ts` for sending queries, receiving answers, and rendering citations.

### Design
- Tailwind CSS utilities for responsive layouts.
- Accessible components and mobile-friendly UI.
- Simple state management using React hooks and local state or context.
- Use streaming responses or polling for long-running chat/processing operations if needed.

## 11. Testing Strategy

### Backend tests
- Unit tests for auth, document service, retrieval service, conversation service, and RAG logic.
- API tests using FastAPI `TestClient`/`AsyncClient` for auth, document upload, status, conversation, and health routes.
- Integration tests with PostgreSQL and Redis to verify database persistence, vector search, and Celery task execution.
- Evaluation tests that assert retrieval quality and answer generation against a representative dataset.

### Parser and RAG tests
- Document parsing tests for PyMuPDF extraction, page structure, and OCR fallback.
- Chunking tests for parent-child relationship and metadata assignment.
- Embedding service tests for provider abstraction and consistent vector shapes.
- Hybrid ranking tests for reciprocal rank fusion and metadata filtering.
- Answer generation tests for grounded response formatting and citation inclusion.

### Frontend tests
- Basic smoke tests for page rendering and API integration interfaces.
- Component-level tests for upload form, document listing, and chat UI if time permits.

### Test data and tooling
- Use fixtures for sample PDF documents and parsed content.
- Include a small evaluation dataset of queries, expected answer snippets, and citation expectations.
- Use coverage reporting to ensure critical RAG and security paths are tested.

## 12. Docker / Deployment Architecture

### Service containers
- `backend` service for FastAPI app.
- `frontend` service for Vite-built static app or dev server.
- `worker` service for Celery worker.
- `redis` service for Celery broker and result backend.
- `postgres` service for data storage.

### Compose and environment
- `docker-compose.yml` defines all services and shared network.
- `.env.example` exposes environment variables for JWT secret, database URL, Redis URL, Gemini API key, storage config.
- Backend and worker share the same PostgreSQL and Redis connections.
- Local filesystem storage volume mounted into backend and worker.

### Deployment considerations
- Use production-ready `Dockerfile` with dependency caching and build optimization.
- Support separate development and production compose overrides.
- Keep secrets out of source control and load them from environment variables or secret management.

## 13. Observability

- Structured logging in backend and worker using JSON-friendly log format.
- Health endpoints for liveness and readiness.
- Processing failure tracking in document status records and worker logs.
- Performance metrics for request latency, task execution time, and retrieval timings.
- Audit logs for document uploads, deletion, and access authorization failures.

## 14. Security Considerations

- Use JWT authentication and secure password hashing (e.g. Argon2 or bcrypt).
- Validate uploaded files by MIME type, size, and content structure.
- Enforce authorization at every service boundary: users may only access their own documents, conversations, and retrieval results.
- Protect environment variables for API keys and database credentials.
- Do not include secrets in logs, responses, or stored messages.
- Validate all API input through Pydantic models and use strict request schemas.
- Use HTTPS in production and secure cookie/session handling if web auth state is stored in frontend.

## Implementation Phases and Dependencies

### Phase 0: Foundation
- Initialize repo structure, `pyproject.toml`, frontend scaffold, Docker Compose, `.env.example`.
- Implement backend core config, logging, database session, and authentication.
- Build storage abstraction and local file storage implementation.
- Create basic auth and health endpoints.

### Phase 1: Document Management and Ingestion
- Implement document upload endpoint and duplicate detection.
- Add document metadata model, processing status, and storage of original files.
- Build Celery worker integration and document ingestion task skeleton.
- Implement PDF parsing with PyMuPDF and page/section extraction.
- Add text normalization, chunking, and metadata enrichment.

### Phase 2: Embeddings and Vector Persistence
- Implement embedding provider abstraction with BAAI/bge-small-en-v1.5.
- Persist child chunk embeddings in PostgreSQL with pgvector.
- Create retrieval service with semantic vector search and keyword search support.
- Add metadata filtering and Reciprocal Rank Fusion.

### Phase 3: Chat and LLM Answering
- Implement conversation and message models.
- Add chat endpoints and follow-up rewriting architecture.
- Implement LLM provider abstraction with Gemini API.
- Build prompt construction, grounding, and citation output.
- Integrate retrieval service into chat flow and persist responses.

### Phase 4: Frontend and UX
- Implement login, document upload, status, and delete UIs.
- Build chat interface with document-scoped conversation support.
- Add document management dashboard, status polling, and citation display.

### Phase 5: Evaluation, Testing, and Reliability
- Add evaluation dataset and regression testing pipeline.
- Implement end-to-end integration tests.
- Add health/readiness, metrics, structured logs, and failure tracking.
- Harden security checks, authorization fences, and upload validation.

### Phase 6: Deployment and Scaling
- Finalize Dockerfiles and compose configuration.
- Document local development and production deployment instructions.
- Prepare the system for future S3 storage, additional document types, and alternative LLM providers.

### Dependency notes
- Authentication and DB schema are prerequisites before document and chat functionality.
- Storage abstraction must be ready before file upload and worker ingestion.
- Retrieval service depends on chunking, embedding generation, and persistent vector storage.
- Chat and conversation depend on retrieval and LLM provider abstractions.

## Conclusion

This plan defines a production-oriented architecture with clearly separated frontend, backend, and worker services. It emphasizes modularity, testability, security, and observability while supporting enterprise RAG requirements, hybrid retrieval, grounded generation, and future extensibility.
