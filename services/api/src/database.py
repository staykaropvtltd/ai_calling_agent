import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from src.config import DATABASE_URL, DB_SSL_REQUIRED

# Supabase Supavisor (connection pooler) terminates TLS with a certificate
# chain that includes an intermediate CA not in the Alpine/Debian system
# trust store.  Using CERT_NONE keeps transport encryption while skipping
# server-identity verification — equivalent to PostgreSQL sslmode=require.
# Full sslmode=verify-full would need the Supabase CA bundle added to the
# image, which is not worth the Dockerfile complexity for this pooler hop.
if DB_SSL_REQUIRED:
    _ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    _connect_args: dict = {"ssl": _ssl_ctx}
else:
    _connect_args = {}

engine = create_async_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

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
