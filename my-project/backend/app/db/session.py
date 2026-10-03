"""Async database engine and session factory.

Usage
-----
FastAPI dependency (preferred)::

    from app.db.session import get_db_session
    from sqlalchemy.ext.asyncio import AsyncSession
    from fastapi import Depends

    @router.get("/example")
    async def example(db: AsyncSession = Depends(get_db_session)):
        result = await db.execute(...)

Direct session (background tasks, tests)::

    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        async with session.begin():
            ...
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _build_engine() -> AsyncEngine:
    """Create the async SQLAlchemy engine from the configured DATABASE_URL.

    Engine options:
    - ``pool_pre_ping=True``   — validate connections before use; drops stale
                                  connections silently rather than raising.
    - ``pool_size=10``         — baseline connection pool (suits the default
                                  Uvicorn worker count).
    - ``max_overflow=20``      — allow burst headroom above pool_size.
    - ``pool_recycle=1800``    — recycle connections every 30 min to avoid
                                  server-side timeout issues.
    - ``echo=settings.debug``  — log SQL statements only when debug mode is on.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
    )
    logger.info(
        "database_engine_created",
        driver=engine.dialect.name,
        environment=settings.environment,
    )
    return engine


engine: AsyncEngine = _build_engine()

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # expire_on_commit=False keeps ORM objects usable after commit without
    # triggering lazy loads (which are not supported by asyncio SQLAlchemy).
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` for use as a FastAPI dependency.

    The session is automatically closed at the end of the request.
    The caller is responsible for committing or rolling back explicitly —
    the dependency does *not* auto-commit so that errors in the response
    serialisation phase cannot silently commit partial state.

    Example::

        @router.post("/items")
        async def create_item(db: AsyncSession = Depends(get_db_session)):
            db.add(Item(...))
            await db.commit()
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
