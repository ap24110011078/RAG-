# RAG Document Chatbot — AI Build Guide

This document turns the **Simplified RAG Chatbot Guide** into a step-by-step implementation plan for an AI coding agent (or developer using AI). Each step includes **what to build**, **why it matters**, **concrete tasks**, **suggested stack**, and **done-when criteria** so work can proceed in order without reading source code first.

---

## Project Overview

**Goal:** Build an enterprise-grade **Retrieval-Augmented Generation (RAG) chatbot** that lets users upload documents (PDF, Office), ask questions, and receive **grounded answers with citations**.

**End-to-end flow:**

```
Upload → Background Processing → Parse → Normalize → Chunk → Enrich → Embed → Store
  → Hybrid Retrieve → LLM Answer with Citations → Conversation Management → Evaluation → Monitoring
```

**Primary use cases:** procurement documents, tenders, compliance, and any scenario where answers must be traceable to source text.

---

## Recommended Tech Stack (defaults for AI to use unless user specifies otherwise)

| Layer | Suggested choice |
|---|---|
| API / backend | Python + FastAPI |
| Database | PostgreSQL 15+ with **pgvector** extension |
| Blob storage | Azure Blob Storage, AWS S3, or MinIO (local dev) |
| Background jobs | Celery + Redis, or FastAPI BackgroundTasks + a job queue |
| PDF/Office parsing | Unstructured, PyMuPDF, or Docling |
| OCR (optional) | Tesseract or Azure Document Intelligence |
| Embeddings | OpenAI `text-embedding-3-small`, or local model via sentence-transformers |
| LLM | OpenAI GPT-4o / Azure OpenAI, or compatible API |
| Hybrid search | pgvector (semantic) + PostgreSQL full-text search (keyword) |
| Frontend (optional) | React/Next.js or Streamlit for MVP |

---

## Step 1: Prepare the Infrastructure

### What
Set up PostgreSQL with pgvector, blob storage, an embedding service, and an LLM API connection.

### Why
These are the foundation. Without vector storage, document storage, embeddings, and an LLM, the system cannot ingest, search, or answer questions.

### AI tasks
1. Create a project scaffold (`backend/`, `worker/`, `frontend/` if needed).
2. Add `docker-compose.yml` with:
   - PostgreSQL + pgvector
   - Redis (for job queue)
   - MinIO (optional, for local blob storage)
3. Define environment variables:
   - `DATABASE_URL`
   - `BLOB_STORAGE_CONNECTION`
   - `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`
   - `LLM_API_KEY` / `LLM_MODEL`
4. Create a health-check endpoint (`GET /health`) that verifies DB, blob, embedding, and LLM connectivity.
5. Run DB migrations to enable `CREATE EXTENSION vector;`.

### Done when
- All services start via Docker.
- Health check returns OK for every dependency.
- A test embedding and test LLM call succeed.

---

## Step 2: Upload and Register the Document

### What
When a user uploads a file: save the original in blob storage, create a DB record, check duplicates, and return immediately.

### Why
Upload must be fast. Heavy parsing runs in the background so users are not blocked on large files.

### AI tasks
1. Create `documents` table:
   - `id`, `filename`, `content_hash`, `blob_path`, `status` (UPLOADED | PROCESSING | APPROVED | FAILED), `created_at`, `error_message`
2. Implement `POST /documents/upload`:
   - Accept PDF, DOCX, XLSX (configurable).
   - Compute SHA-256 hash of file bytes.
   - Reject duplicate uploads (same hash + same tenant/user scope).
   - Upload raw file to blob storage.
   - Insert DB row with status `UPLOADED`.
   - Enqueue background processing job.
   - Return `{ document_id, status: "UPLOADED" }` immediately.
3. Implement `GET /documents/{id}` for status polling.

### Done when
- File upload completes in under a few seconds for large PDFs.
- Duplicate file returns 409 or a clear message.
- UI/API can poll status without waiting for parsing.

---

## Step 3: Process the Document in the Background

### What
A background worker claims the document, sets status to `PROCESSING`, parses the file, then marks it `APPROVED` or `FAILED`.

### Why
Prevents duplicate processing, improves reliability, and lets the UI show accurate progress.

### AI tasks
1. Create a worker process (Celery task or async job runner).
2. Implement **claim logic**:
   - `SELECT ... FOR UPDATE SKIP LOCKED` or equivalent so only one worker processes a document.
   - Set status → `PROCESSING` at claim time.
3. Wrap the full pipeline (Steps 4–9) in try/except:
   - On success → `APPROVED`
   - On failure → `FAILED` + store error message
4. Add idempotency: re-running a failed document should safely re-process or clean up partial data.
5. Expose optional progress events (e.g., `PARSING`, `CHUNKING`, `EMBEDDING`).

### Done when
- Two workers cannot process the same document twice.
- Failed jobs surface a readable error in the DB/API.
- Re-ingestion of a document replaces old chunks cleanly.

---

## Step 4: Parse the PDF or Office Document

### What
Extract headings, paragraphs, tables, and page numbers. Enable accurate table extraction and optional OCR for scanned files.

### Why
Parsing quality directly affects retrieval and answer quality. Bad table/heading extraction leads to wrong answers.

### AI tasks
1. Build a `DocumentParser` interface with one method: `parse(file_path) -> ParsedDocument`.
2. `ParsedDocument` should contain ordered **blocks**:
   - `type`: heading | paragraph | table | list
   - `text`: normalized string
   - `page_number`: int
   - `heading_path`: list of ancestor headings (e.g., `["Section 3", "Eligibility"]`)
   - `table_html` or structured rows (for tables)
3. Integrate a parser library (Unstructured, Docling, or PyMuPDF + python-docx).
4. Detect scanned PDFs (no extractable text) and route to OCR pipeline.
5. Unit-test on sample PDFs with tables, multi-column layout, and headings.

### Done when
- Headings preserve hierarchy.
- Tables are extracted as structured data, not garbled text.
- Scanned PDFs trigger OCR when enabled.

---

## Step 5: Clean and Normalize the Extracted Text

### What
Normalize whitespace, punctuation, Unicode, line breaks, and legacy font encodings before embedding.

### Why
Visually identical clauses must produce identical text so search and duplicate detection work reliably.

### AI tasks
1. Create `normalize_text(text: str) -> str`:
   - Collapse repeated whitespace.
   - Normalize Unicode (NFKC).
   - Fix common OCR artifacts (e.g., `l` vs `1` where safe).
   - Standardize quotes, dashes, and bullet characters.
   - Remove zero-width characters.
2. Apply normalization to every block before chunking.
3. Store both **raw** and **normalized** text if citations must show original formatting.

### Done when
- Same clause from two parsing paths produces the same normalized string.
- Normalization is applied consistently at ingestion and query time.

---

## Step 6: Create Parent and Child Chunks

### What
Split the document into **parent sections** (large) and **child chunks** (small). Embed child chunks; send parent chunks to the LLM as context.

### Why
Small chunks improve retrieval precision; large parents preserve meaning for the final answer.

### AI tasks
1. Define chunking strategy:
   - **Parent:** split by heading sections (e.g., 1500–3000 tokens).
   - **Child:** split parents further (e.g., 300–500 tokens with 50-token overlap).
2. Create tables:
   - `parent_chunks`: `id`, `document_id`, `text`, `heading_path`, `page_start`, `page_end`
   - `child_chunks`: `id`, `parent_chunk_id`, `text`, `token_count`, `chunk_index`
3. Ensure chunks do not break mid-sentence when possible.
4. Attach `parent_chunk_id` on every child for retrieval → context mapping.

### Done when
- Every child chunk links to exactly one parent.
- Chunk sizes stay within configured token limits.
- Overlap prevents lost context at boundaries.

---

## Step 7: Enrich the Chunks with Metadata

### What
Attach headings, page numbers, document type, section type, and business metadata to every chunk.

### Why
Metadata enables filtering, better ranking, and verifiable citations.

### AI tasks
1. Extend chunk records with JSON metadata, e.g.:
   ```json
   {
     "document_id": "...",
     "document_type": "tender",
     "heading_path": ["Section 2", "Eligibility"],
     "page_number": 14,
     "section_type": "table",
     "source_filename": "RFP_2026.pdf"
   }
   ```
2. Derive `document_type` from filename, folder, or user tag.
3. Build citation strings: `"RFP_2026.pdf, Section 2 > Eligibility, p. 14"`.
4. Index frequently filtered fields (document_id, document_type, page_number).

### Done when
- Every chunk returned by search includes enough metadata to render a citation.
- API supports filters like `document_id`, `document_type`, date range.

---

## Step 8: Generate Embeddings

### What
Send cleaned **child chunks** to the embedding model. Use the **same model and dimensions** at ingestion and query time.

### Why
Embeddings enable semantic search. Different models at ingest vs query make vector comparison invalid.

### AI tasks
1. Create `EmbeddingService`:
   - `embed_texts(texts: list[str]) -> list[list[float]]`
   - Batch requests (e.g., 100 chunks per call).
   - Retry with exponential backoff on rate limits.
2. Store config in one place: `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`.
3. Create `embeddings` table or column on `child_chunks`:
   - `child_chunk_id`, `embedding vector(1536)` (match model dims)
4. Validate vector length before insert.

### Done when
- All child chunks have embeddings after ingestion.
- Query embeddings use the identical model/settings.
- Batch embedding handles 10k+ chunks without OOM.

---

## Step 9: Store the Processed Data

### What
Persist documents, parent chunks, child chunks, embeddings, and searchable text indexes in PostgreSQL using transactional inserts.

### Why
Proper storage ensures fast retrieval, data integrity, and efficient re-ingestion on updates.

### AI tasks
1. Wrap ingestion in a **single transaction** per document:
   - Delete old chunks for re-ingestion.
   - Insert parents → children → embeddings.
   - Commit only if all succeed.
2. Add indexes:
   - `ivfflat` or `hnsw` index on embedding column (pgvector).
   - GIN index on `to_tsvector('english', text)` for keyword search.
   - B-tree indexes on `document_id`, metadata fields.
3. Add `updated_at` and versioning if documents can be replaced.

### Done when
- Ingestion is atomic (no orphan chunks on failure).
- Vector and keyword queries run in under ~200ms for typical corpora.
- Re-uploading a document replaces prior chunks cleanly.

---

## Step 10: Retrieve Relevant Content

### What
For each user query: run semantic vector search, keyword search, optional metadata boosting, combine with **Reciprocal Rank Fusion (RRF)**, return top **parent** sections.

### Why
Hybrid retrieval beats vector-only or keyword-only. It handles both conceptual questions and exact terms (GSTIN, certificate names, rule numbers).

### AI tasks
1. Create `RetrievalService.search(query, filters, top_k)`:
   - **Vector search:** embed query → cosine similarity on child chunks → map to parents.
   - **Keyword search:** PostgreSQL `ts_rank` / BM25-style ranking on child text.
   - **Metadata boost:** optional score multiplier for matching document_type, tender_id, etc.
2. Implement **RRF** to merge ranked lists:
   ```
   score(d) = sum( 1 / (k + rank_i(d)) )  for each ranker i, k=60 typical
   ```
3. Deduplicate by `parent_chunk_id`; return top N parents with their best-matching children.
4. Apply minimum similarity threshold to reduce noise.

### Done when
- Conceptual queries ("What are eligibility criteria?") return relevant sections.
- Exact-term queries ("GSTIN requirement") return correct hits.
- Results include citation metadata for each parent section.

---

## Step 11: Generate the Final Answer

### What
Send retrieved parent sections to the LLM with instructions to answer **only from evidence** and **cite sources** for every important claim.

### Why
Grounding reduces hallucinations — critical for procurement, tender, and compliance workflows.

### AI tasks
1. Build a prompt template:
   ```
   System: You are a document assistant. Answer ONLY using the provided context.
   If the answer is not in the context, say "I don't know based on the provided documents."
   Cite every important statement using [Source: filename, section, page].

   Context:
   {{retrieved_parent_sections_with_citations}}

   User question:
   {{query}}
   ```
2. Implement `POST /chat` or `/query`:
   - Retrieve context (Step 10).
   - Truncate context to fit token budget (prioritize highest RRF scores).
   - Call LLM with temperature ~0.1–0.3.
   - Parse response; attach structured citations array in API response.
3. Refuse to answer when retrieval returns empty or below threshold.

### Done when
- Answers include citations matching retrieved chunks.
- Out-of-scope questions get "not found in documents" instead of invented facts.
- Response JSON includes `answer`, `citations[]`, `sources_used[]`.

---

## Step 12: Manage the Conversation

### What
Store conversation history, rewrite follow-ups into standalone queries, apply document/tender scoping, and cap context sent to the LLM.

### Why
Users ask natural follow-ups ("What about penalties?") but retrieval needs a self-contained query.

### AI tasks
1. Create tables:
   - `conversations`: `id`, `user_id`, `scope` (document_ids / tender_id), `created_at`
   - `messages`: `id`, `conversation_id`, `role`, `content`, `created_at`
2. On each user message:
   - Load recent history (last N turns).
   - **Query rewriting:** use LLM or rules to expand follow-up → standalone question.
     - Example: "What about penalties?" → "What penalties apply for late delivery in Tender XYZ?"
   - Apply scope filters from conversation settings.
   - Retrieve + generate answer (Steps 10–11).
   - Save user message and assistant reply.
3. Enforce token limits: trim old history, summarize if needed.

### Done when
- Follow-up questions retrieve correct context without requiring the user to repeat the subject.
- Conversations can be scoped to one tender or a set of documents.
- Token usage stays within model limits.

---

## Step 13: Evaluate the System

### What
Maintain a gold dataset of real business questions; measure retrieval recall and answer quality; rerun when chunking, embeddings, or prompts change.

### Why
Evaluation is the only reliable way to catch regressions and prove improvements.

### AI tasks
1. Create `eval/gold_dataset.jsonl`:
   ```json
   {"question": "...", "expected_doc_ids": ["..."], "expected_answer_contains": ["..."], "filters": {}}
   ```
2. Build an eval script:
   - Run retrieval → compute **Recall@k** (expected doc/chunk in top k).
   - Run full RAG → score answer with exact match, LLM-as-judge, or human rubric.
   - Output CSV/JSON report with per-question scores.
3. Add CI job or manual command: `python -m eval.run --dataset eval/gold_dataset.jsonl`.
4. Version the dataset; add new failure cases whenever users report bad answers.

### Done when
- Baseline metrics exist before tuning.
- Any change to chunking/embeddings/prompts triggers a re-run.
- Regressions are visible in the eval report.

---

## Step 14: Operate and Monitor the System

### What
Add health checks, structured logging, performance metrics, failure tracking, and re-ingestion for bad documents.

### Why
Production systems need visibility to diagnose parsing failures, OCR issues, and embedding outages quickly.

### AI tasks
1. **Logging:** structured JSON logs with `document_id`, `job_id`, `step`, `duration_ms`, `error`.
2. **Metrics:** Prometheus or similar — upload count, processing latency, retrieval latency, LLM latency, failure rate by step.
3. **Alerts:** failed document rate spike, embedding/LLM API errors, queue backlog.
4. **Admin endpoints:**
   - `POST /documents/{id}/reingest` — re-queue failed/stale documents.
   - `GET /admin/failures` — list recent FAILED documents with errors.
5. **Dashboards:** Grafana or simple admin UI for job status and eval trends.

### Done when
- Operators can see why a document failed without reading logs manually.
- Re-ingest fixes bad parses without redeploying code.
- p95 latency is tracked for upload, retrieval, and chat.

---

## Suggested Repository Layout

```
rag-chatbot/
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── api/
│   │   │   ├── documents.py     # upload, status
│   │   │   ├── chat.py          # query + conversation
│   │   │   └── health.py
│   │   ├── services/
│   │   │   ├── parser.py
│   │   │   ├── normalizer.py
│   │   │   ├── chunker.py
│   │   │   ├── embedder.py
│   │   │   ├── retrieval.py
│   │   │   └── llm.py
│   │   ├── models/              # SQLAlchemy / DB models
│   │   └── db/
│   │       └── migrations/
│   └── requirements.txt
├── worker/
│   ├── tasks.py                 # background ingestion pipeline
│   └── worker.py
├── eval/
│   ├── gold_dataset.jsonl
│   └── run.py
└── frontend/                    # optional
```

---

## AI Agent Execution Order

When an AI agent builds this project, follow this strict sequence:

| Order | Step | Depends on |
|---|---|---|
| 1 | Infrastructure (Step 1) | — |
| 2 | Upload API (Step 2) | Step 1 |
| 3 | Background worker shell (Step 3) | Steps 1–2 |
| 4 | Parser (Step 4) | Step 3 |
| 5 | Normalizer (Step 5) | Step 4 |
| 6 | Chunker (Step 6) | Step 5 |
| 7 | Metadata enrichment (Step 7) | Step 6 |
| 8 | Embeddings (Step 8) | Step 7 |
| 9 | Storage + indexes (Step 9) | Step 8 |
| 10 | Hybrid retrieval (Step 10) | Step 9 |
| 11 | LLM answer + citations (Step 11) | Step 10 |
| 12 | Conversation management (Step 12) | Step 11 |
| 13 | Evaluation suite (Step 13) | Step 11 |
| 14 | Monitoring + re-ingest (Step 14) | All |

**Rule for the AI agent:** Do not skip ahead. Each step should be testable in isolation before moving to the next.

---

## Prompt Template for AI to Start Each Step

Use this when asking an AI coding agent to implement a step:

```
Implement Step [N]: [Step Name] for the RAG Document Chatbot.

Context:
- Follow AI_Project_Build_Guide.md in this repo.
- Use the recommended stack unless I specify otherwise.
- Match existing code style and folder layout.
- Write the minimum code needed; add tests only where specified in "Done when".

Deliverables:
1. Code changes for this step only
2. Brief explanation of what was added
3. How to test manually (curl commands or script)
4. Confirmation of "Done when" criteria

Do not implement later steps yet.
```

---

## Quick Reference Summary

| Step | Name | One-line description |
|---|---|---|
| 1 | Infrastructure | PostgreSQL + pgvector, blob storage, embedding + LLM APIs |
| 2 | Upload | Fast upload, blob save, DB record, duplicate check |
| 3 | Background processing | Worker claims job, updates status, runs pipeline |
| 4 | Parse | Extract headings, paragraphs, tables, pages (+ OCR) |
| 5 | Normalize | Clean text before embedding |
| 6 | Chunk | Parent sections + child chunks for retrieval |
| 7 | Enrich metadata | Headings, pages, doc type for filters and citations |
| 8 | Embed | Vectorize child chunks with consistent model |
| 9 | Store | Transactional DB writes + vector/FTS indexes |
| 10 | Retrieve | Hybrid vector + keyword search with RRF |
| 11 | Generate answer | LLM grounded on retrieved context with citations |
| 12 | Conversation | History, query rewriting, scoping, token limits |
| 13 | Evaluate | Gold dataset, recall + answer quality metrics |
| 14 | Operate | Logging, metrics, alerts, re-ingestion |

---

*Generated from `Simplified_RAG_Chatbot_Guide.docx` — expanded for AI-driven implementation.*
