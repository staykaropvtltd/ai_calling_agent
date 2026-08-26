import contextlib
import ssl
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from src.config import DATABASE_URL, DB_SSL_REQUIRED


def build_engine(url: str) -> AsyncEngine:
    """Build an async engine with this app's standard SSL handling.

    Shared by the app's own `engine` below and by alembic/env.py, which
    builds a second engine against MIGRATION_DATABASE_URL (NK-07) — the two
    intentionally use different roles, so they cannot share one engine.
    """
    # Supabase Supavisor (connection pooler) terminates TLS with a certificate
    # chain that includes an intermediate CA not in the Alpine/Debian system
    # trust store.  Using CERT_NONE keeps transport encryption while skipping
    # server-identity verification — equivalent to PostgreSQL sslmode=require.
    # Full sslmode=verify-full would need the Supabase CA bundle added to the
    # image, which is not worth the Dockerfile complexity for this pooler hop.
    if DB_SSL_REQUIRED:
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args: dict = {"ssl": ssl_ctx}
    else:
        connect_args = {}

    return create_async_engine(
        url,
        connect_args=connect_args,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )


engine = build_engine(DATABASE_URL)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            # NK-07: get_tenant_scoped_db/get_internal_service_db (src/tenant.py)
            # set app.current_tenant with set_config(..., false) — session-scoped,
            # not SET LOCAL — because a request that commits mid-handler (the
            # create-then-refresh pattern used throughout routers/admin.py) would
            # otherwise lose its tenant context the moment SET LOCAL's owning
            # transaction ends, well before the request itself is done. Session
            # scope survives that, but must be explicitly cleared here before the
            # underlying connection returns to the pool — the exact "next
            # request on a recycled connection inherits the previous tenant's
            # context" leak the Database Design doc warns SET LOCAL exists to
            # prevent, now our responsibility to prevent by hand instead.
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                with contextlib.suppress(Exception):
                    await session.execute(text("RESET app.current_tenant"))
