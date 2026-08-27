# Environment vars must be set BEFORE any src.* import so that module-level
# code in src.config and src.database picks up the test values.
import os

os.environ["JWT_SECRET_KEY"] = "test-secret-key-not-for-production-only"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DB_SSL_REQUIRED"] = "false"
# Use a parseable URL (services/api guards with `if REDIS_URL else None`).
# app/services/redis_service.py parses the URL at import time — empty string
# would cause a ValueError. localhost:6379 is valid syntax; no Redis is
# actually contacted because admin tests never invoke Redis-touching endpoints.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ["API_SECRET_KEY"] = "test-admin-password"
os.environ["API_USERNAME"] = "admin"
os.environ["API_PASSWORD"] = "test-admin-password"
os.environ["API_ADMIN_EMAIL"] = "admin@staykaro.com"
os.environ["API_ADMIN_FULL_NAME"] = "Test Admin"
os.environ["INTERNAL_API_TOKEN"] = "test-internal-api-token-not-for-production"

from datetime import UTC, datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from jose import jwt  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
_JWT_SECRET = "test-secret-key-not-for-production-only"
_JWT_ALG = "HS256"
INTERNAL_API_TOKEN = "test-internal-api-token-not-for-production"


def _make_token(role: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=30)
    return jwt.encode(
        {"sub": "test", "role": role, "exp": expire, "type": "access"},
        _JWT_SECRET,
        _JWT_ALG,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def db_session():
    """Fresh in-memory SQLite database for each test."""
    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def api_client(db_session: AsyncSession):
    """AsyncClient with DB dependency overridden to use the test SQLite session."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # /internal/v1/* requires this header (src/routers/internal.py). Setting
    # it as a default here means the existing internal-API business-logic
    # tests (create/get/finalize/phone-routes) don't need per-call changes;
    # test_internal_auth.py exercises the missing/wrong-token paths directly.
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"X-Internal-API-Token": INTERNAL_API_TOKEN},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def super_admin_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token('super_admin')}"}


@pytest.fixture
def user_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token('user')}"}


@pytest.fixture
def agent_headers() -> dict:
    return {"Authorization": f"Bearer {_make_token('agent')}"}


@pytest.fixture
def make_tenant_admin_headers():
    """Factory fixture: call with a client_id to get headers for that tenant's admin."""

    def _make(client_id: int) -> dict:
        expire = datetime.now(UTC) + timedelta(minutes=30)
        token = jwt.encode(
            {
                "sub": "ta@test.com",
                "role": "tenant_admin",
                "client_id": client_id,
                "exp": expire,
                "type": "access",
            },
            _JWT_SECRET,
            _JWT_ALG,
        )
        return {"Authorization": f"Bearer {token}"}

    return _make
