"""Alembic environment script — async PostgreSQL edition.

This file is executed by every ``alembic`` CLI invocation.  It wires together:
- The database URL from the project's ``Settings`` object (never hardcoded).
- The ``Base.metadata`` that describes all ORM models so Alembic can diff
  the schema automatically.
- The SQLAlchemy *async* engine via ``run_async_migrations`` so the
  ``asyncpg`` driver works correctly.

Offline mode (``alembic upgrade --sql``) still works because offline mode
never opens a real connection.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
# Import Base *and* all models so that Base.metadata is fully populated.
# If any model is not imported here, Alembic will not see its table and will
# drop it when autogenerating a migration.
from app.core.config import settings
from app.db.base import Base
from app.db import models as _models  # noqa: F401 — side-effect import registers all tables

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini.
# ---------------------------------------------------------------------------
config = context.config

# Inject the database URL from Settings so it is never stored in alembic.ini.
# asyncpg needs the postgresql+asyncpg:// scheme; Alembic works with it fine.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic diffs against the live database.
target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations  (``alembic upgrade --sql``)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Emit SQL to stdout without an actual DB connection.

    Useful for reviewing what a migration will do or applying changes via a
    DBA-controlled SQL script.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Render AS is important for pgvector column types.
        render_as_batch=False,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations — async path (asyncpg)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Execute migrations inside a synchronous connection context.

    Called from ``run_async_migrations`` below after the async engine
    yields a sync connection via ``run_sync``.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Include schemas if we ever add PostgreSQL schemas beyond public.
        include_schemas=False,
        # Render the pgvector VECTOR type correctly.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a sync bridge.

    ``run_sync`` bridges between asyncio and Alembic's synchronous migration
    runner without blocking the event loop.
    """
    # Build a *separate* engine for migrations — not the application engine —
    # so migration runs do not interfere with the connection pool used by the
    # running API process.  NullPool ensures connections are closed immediately
    # after each migration operation.
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online (connected) migration runs."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
