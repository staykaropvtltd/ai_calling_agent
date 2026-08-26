import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection

# services/api/ (the directory containing alembic.ini) must be on sys.path
# so `import src...` resolves the same way it does when uvicorn runs the app.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import DATABASE_URL, to_asyncpg_url  # noqa: E402
from src.database import Base, build_engine  # noqa: E402
from src.models import (  # noqa: E402, F401 — import registers every model on Base.metadata
    AuditLog,
    Call,
    Caller,
    CallEvent,
    CallTurn,
    Client,
    PhoneNumberRoute,
    User,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# NK-07: migrations run DDL (CREATE ROLE, ALTER TABLE ... FORCE ROW LEVEL
# SECURITY) that the restricted staykaro_app runtime role must not be able to
# do — so migrations connect with MIGRATION_DATABASE_URL (superuser) when set,
# falling back to DATABASE_URL / SUPABASE_DB_URL (src.config) for anyone not
# using the split yet. Never hand-maintain this separately in alembic.ini, or
# dev/CI could silently migrate a different database than the app connects to.
_MIGRATION_URL = to_asyncpg_url(os.environ.get("MIGRATION_DATABASE_URL", "")) or DATABASE_URL
if _MIGRATION_URL:
    config.set_main_option("sqlalchemy.url", _MIGRATION_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against _MIGRATION_URL (the superuser/migration role).

    Deliberately a *separate* engine from src.database.engine (the app's own,
    built from DATABASE_URL — the restricted staykaro_app role once NK-07's
    role split is configured): reusing the app's engine would mean DDL like
    `ALTER TABLE ... FORCE ROW LEVEL SECURITY` runs as a role that may not
    have privileges for it, or — worse, before the split — silently as the
    same superuser RLS is supposed to restrict. build_engine() still gives us
    the same SSL/pooling behaviour as the app (Supabase Supavisor TLS note in
    src/database.py). NullPool isn't needed here since this process runs once
    and exits.
    """
    migration_engine = build_engine(_MIGRATION_URL)
    async with migration_engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await migration_engine.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
