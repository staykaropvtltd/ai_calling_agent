"""
Phase 2 — /internal/v1/* authentication (src/routers/internal.py::verify_internal_token).

api_client (conftest.py) sends a valid X-Internal-API-Token by default so the
business-logic tests in test_internal_calls.py / test_phone_routes.py don't need
per-call changes. This file exercises the auth boundary itself directly, with
its own AsyncClient instances so each test controls exactly what header (if
any) is sent.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.main import app

pytestmark = pytest.mark.asyncio

_BASE = "/internal/v1"
# Must match conftest.py's INTERNAL_API_TOKEN and the INTERNAL_API_TOKEN env
# var conftest.py sets before src.config is ever imported.
_VALID_TOKEN = "test-internal-api-token-not-for-production"
_CALL_PAYLOAD = {
    "call_id": "auth-check-call",
    "tenant_id": "tenant-1",
    "agent_id": "agent-1",
    "started_at": "2026-01-01T10:00:00+00:00",
}


@pytest.fixture
async def unauthenticated_client(db_session: AsyncSession):
    """Same DB override as api_client, but with no default headers at all."""

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def test_missing_token_rejected(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(f"{_BASE}/calls", json=_CALL_PAYLOAD)
    assert response.status_code == 401
    assert "internal api token" in response.json()["detail"].lower()


async def test_wrong_token_rejected(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        f"{_BASE}/calls",
        json=_CALL_PAYLOAD,
        headers={"X-Internal-API-Token": "not-the-right-token"},
    )
    assert response.status_code == 401


async def test_empty_token_rejected(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        f"{_BASE}/calls",
        json=_CALL_PAYLOAD,
        headers={"X-Internal-API-Token": ""},
    )
    assert response.status_code == 401


async def test_valid_token_is_accepted(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        f"{_BASE}/calls",
        json=_CALL_PAYLOAD,
        headers={"X-Internal-API-Token": _VALID_TOKEN},
    )
    assert response.status_code == 201
    assert response.json()["call_id"] == "auth-check-call"


async def test_missing_token_rejected_on_get_call(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.get(f"{_BASE}/calls/whatever")
    assert response.status_code == 401


async def test_missing_token_rejected_on_finalize(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.post(
        f"{_BASE}/calls/whatever/finalize",
        json={"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "caller_hangup"},
    )
    assert response.status_code == 401


async def test_missing_token_rejected_on_phone_routes(unauthenticated_client: AsyncClient) -> None:
    response = await unauthenticated_client.get(f"{_BASE}/phone-routes/+919999999999")
    assert response.status_code == 401


async def test_no_configured_token_fails_closed(
    unauthenticated_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a request that sends *some* token must be rejected if
    INTERNAL_API_TOKEN itself isn't configured — fail closed, not open."""
    import src.routers.internal as internal_module

    monkeypatch.setattr(internal_module, "INTERNAL_API_TOKEN", "")
    response = await unauthenticated_client.post(
        f"{_BASE}/calls",
        json=_CALL_PAYLOAD,
        headers={"X-Internal-API-Token": "anything-at-all"},
    )
    assert response.status_code == 401
