"""
SH-02 — Internal call lifecycle API tests.
Covers: create, lookup, finalize, idempotency, not-found, duplicates.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Call

pytestmark = pytest.mark.asyncio

_BASE = "/internal/v1"
_T0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _call_payload(**overrides) -> dict:
    base = {
        "call_id": "call-abc-123",
        "tenant_id": "tenant-1",
        "agent_id": "agent-1",
        "started_at": "2026-01-01T10:00:00+00:00",
    }
    base.update(overrides)
    return base


async def _seed_call(db: AsyncSession, *, call_id="seeded-call", **kwargs) -> Call:
    call = Call(
        call_id=call_id,
        tenant_id=kwargs.get("tenant_id", "tenant-1"),
        agent_id=kwargs.get("agent_id", "agent-1"),
        provider_call_id=kwargs.get("provider_call_id"),
        started_at=kwargs.get("started_at", _T0),
        status=kwargs.get("status", "active"),
        ended_at=kwargs.get("ended_at"),
        end_reason=kwargs.get("end_reason"),
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


# ── POST /internal/v1/calls ───────────────────────────────────────────────────


async def test_create_call_returns_201(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{_BASE}/calls", json=_call_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["call_id"] == "call-abc-123"
    assert body["tenant_id"] == "tenant-1"
    assert body["agent_id"] == "agent-1"
    assert body["status"] == "active"


async def test_create_call_with_provider_call_id(api_client: AsyncClient) -> None:
    payload = _call_payload(call_id="call-with-provider", provider_call_id="exo-sid-001")
    response = await api_client.post(f"{_BASE}/calls", json=payload)
    assert response.status_code == 201
    assert response.json()["call_id"] == "call-with-provider"


async def test_create_call_duplicate_returns_409(api_client: AsyncClient) -> None:
    payload = _call_payload(call_id="dup-call")
    first = await api_client.post(f"{_BASE}/calls", json=payload)
    assert first.status_code == 201
    second = await api_client.post(f"{_BASE}/calls", json=payload)
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


async def test_create_call_missing_required_fields_returns_422(api_client: AsyncClient) -> None:
    response = await api_client.post(f"{_BASE}/calls", json={"call_id": "x"})
    assert response.status_code == 422


# ── GET /internal/v1/calls/{call_id} ─────────────────────────────────────────


async def test_get_call_returns_state(api_client: AsyncClient, db_session: AsyncSession) -> None:
    await _seed_call(db_session, call_id="get-me", provider_call_id="exo-42")
    response = await api_client.get(f"{_BASE}/calls/get-me")
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "get-me"
    assert body["status"] == "active"
    assert body["provider_call_id"] == "exo-42"
    assert body["ended_at"] is None
    assert body["end_reason"] is None


async def test_get_call_not_found_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{_BASE}/calls/does-not-exist")
    assert response.status_code == 404


# ── POST /internal/v1/calls/{call_id}/finalize ────────────────────────────────


async def test_finalize_call_marks_completed(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_call(db_session, call_id="fin-call")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "caller_hangup"}
    response = await api_client.post(f"{_BASE}/calls/fin-call/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "fin-call"
    assert body["status"] == "completed"
    assert body["end_reason"] == "caller_hangup"
    assert body["ended_at"] is not None


async def test_finalize_call_provider_failure_marks_failed(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_call(db_session, call_id="fail-call")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "provider_failure"}
    response = await api_client.post(f"{_BASE}/calls/fail-call/finalize", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


async def test_finalize_call_not_found_returns_404(api_client: AsyncClient) -> None:
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "caller_hangup"}
    response = await api_client.post(f"{_BASE}/calls/ghost-call/finalize", json=payload)
    assert response.status_code == 404


async def test_finalize_call_is_idempotent(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_call(db_session, call_id="idem-call")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "caller_hangup"}
    first = await api_client.post(f"{_BASE}/calls/idem-call/finalize", json=payload)
    assert first.status_code == 200
    second = await api_client.post(f"{_BASE}/calls/idem-call/finalize", json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "completed"


async def test_finalize_missing_fields_returns_422(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_call(db_session, call_id="bad-fin")
    response = await api_client.post(f"{_BASE}/calls/bad-fin/finalize", json={})
    assert response.status_code == 422


# ── Full lifecycle ────────────────────────────────────────────────────────────


async def test_full_lifecycle_create_get_finalize_get(api_client: AsyncClient) -> None:
    call_id = "lifecycle-call"
    # 1. Create
    create_resp = await api_client.post(
        f"{_BASE}/calls",
        json=_call_payload(call_id=call_id, provider_call_id="exo-lifecycle"),
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["status"] == "active"

    # 2. Get — active
    get_resp = await api_client.get(f"{_BASE}/calls/{call_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "active"
    assert get_resp.json()["provider_call_id"] == "exo-lifecycle"

    # 3. Finalize
    fin_resp = await api_client.post(
        f"{_BASE}/calls/{call_id}/finalize",
        json={"ended_at": "2026-01-01T10:10:00+00:00", "end_reason": "caller_hangup"},
    )
    assert fin_resp.status_code == 200
    assert fin_resp.json()["status"] == "completed"

    # 4. Get — completed
    final_get = await api_client.get(f"{_BASE}/calls/{call_id}")
    assert final_get.status_code == 200
    body = final_get.json()
    assert body["status"] == "completed"
    assert body["ended_at"] is not None
    assert body["end_reason"] == "caller_hangup"
