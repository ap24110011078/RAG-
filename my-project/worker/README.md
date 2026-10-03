# Background Worker

Celery worker for asynchronous document processing and evaluation tasks.

## Responsibilities

- PDF parsing and ingestion pipeline
- Embedding generation and vector persistence
- Evaluation benchmark runs
- Retry and failure handling

## Development

```bash
cd worker
celery -A celery_worker worker --loglevel=info
```

Requires Redis broker and shared PostgreSQL/storage access with the backend.
