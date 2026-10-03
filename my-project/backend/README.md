# Backend API

FastAPI-based REST API for the Enterprise Document Intelligence Chatbot.

## Responsibilities

- Authentication and authorization (JWT)
- Document upload and management
- Conversation and chat orchestration
- Health checks and observability

## Structure

```
app/
├── api/          # Route handlers (thin controllers)
├── core/         # Config, logging, security, dependencies
├── db/           # Models, sessions, repositories, migrations
├── services/     # Business logic layer
├── storage/      # File storage abstraction
├── tasks/        # Celery task definitions (shared with worker)
└── rag/          # RAG pipeline (parser, retriever, LLM)
```

## Development

```bash
cd backend
pip install -e ".[dev]"
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Testing

```bash
pytest
```
