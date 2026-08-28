import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.config.settings import DATABASE_URL, DB_SSL_REQUIRED

# ── SSL context ───────────────────────────────────────────────────────────────
# Supabase requires TLS. ssl.create_default_context() validates the server
# certificate against the system's trusted CA bundle (correct for production).
_connect_args: dict = {}
if DB_SSL_REQUIRED:
    _ssl_ctx = ssl.create_default_context()
    _connect_args["ssl"] = _ssl_ctx

# ── Async engine ──────────────────────────────────────────────────────────────
# SQLite (test environments) uses StaticPool which rejects pool_size,
# max_overflow, pool_pre_ping, and pool_recycle — those are PostgreSQL-only.
_is_sqlite = DATABASE_URL.startswith("sqlite")
_pool_kwargs: dict = (
    {}
    if _is_sqlite
    else {
        "pool_size": 5,  # connections held open
        "max_overflow": 10,  # extra connections allowed under load
        "pool_pre_ping": True,  # discard stale connections before checkout
        "pool_recycle": 1800,  # recycle connections every 30 min
    }
)
engine = create_async_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    **_pool_kwargs,
    echo=False,  # set True temporarily to log all SQL
)

# ── Session factory ───────────────────────────────────────────────────────────
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # prevents lazy-load errors after commit in async context
)

Base = declarative_base()


# ── FastAPI dependency ────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an AsyncSession per request.
    Rolls back automatically on any unhandled exception.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
