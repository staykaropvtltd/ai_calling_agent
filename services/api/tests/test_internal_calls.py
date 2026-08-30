"""
SH-02 — Internal call lifecycle API tests.
Covers: create, lookup, finalize, idempotency, not-found, duplicates.
Phase 1 additions: is_simulation flag, connection_status, full end_reason coverage.
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
        is_simulation=kwargs.get("is_simulation", False),
        connection_status=kwargs.get("connection_status", "connected"),
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
    assert body["is_simulation"] is False


async def test_create_call_simulation_flag(api_client: AsyncClient) -> None:
    payload = _call_payload(call_id="sim-call", is_simulation=True)
    response = await api_client.post(f"{_BASE}/calls", json=payload)
    assert response.status_code == 201
    assert response.json()["is_simulation"] is True


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
    assert body["connection_status"] == "connected"
    assert body["is_simulation"] is False
    assert body["ended_at"] is None
    assert body["end_reason"] is None


async def test_get_call_not_found_returns_404(api_client: AsyncClient) -> None:
    response = await api_client.get(f"{_BASE}/calls/does-not-exist")
    assert response.status_code == 404


# ── POST /internal/v1/calls/{call_id}/finalize ────────────────────────────────


async def test_finalize_caller_hangup(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """caller_hangup → completed + connected: call ran to natural conclusion."""
    await _seed_call(db_session, call_id="fin-caller-hangup")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "caller_hangup"}
    response = await api_client.post(f"{_BASE}/calls/fin-caller-hangup/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["connection_status"] == "connected"
    assert body["end_reason"] == "caller_hangup"


async def test_finalize_agent_finished(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """agent_finished → completed + connected."""
    await _seed_call(db_session, call_id="fin-agent")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "agent_finished"}
    response = await api_client.post(f"{_BASE}/calls/fin-agent/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["connection_status"] == "connected"


async def test_finalize_provider_failure(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """provider_failure → failed + failed_pre_connect."""
    await _seed_call(db_session, call_id="fin-provider")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "provider_failure"}
    response = await api_client.post(f"{_BASE}/calls/fin-provider/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["connection_status"] == "failed_pre_connect"


async def test_finalize_no_answer(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """no_answer → no_answer + attempted: dialled but nobody picked up."""
    await _seed_call(db_session, call_id="fin-no-answer")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "no_answer"}
    response = await api_client.post(f"{_BASE}/calls/fin-no-answer/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_answer"
    assert body["connection_status"] == "attempted"


async def test_finalize_voicemail(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """voicemail → voicemail + attempted."""
    await _seed_call(db_session, call_id="fin-voicemail")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "voicemail"}
    response = await api_client.post(f"{_BASE}/calls/fin-voicemail/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "voicemail"
    assert body["connection_status"] == "attempted"


async def test_finalize_invalid_number(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """invalid_number → failed + failed_pre_connect."""
    await _seed_call(db_session, call_id="fin-invalid")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "invalid_number"}
    response = await api_client.post(f"{_BASE}/calls/fin-invalid/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["connection_status"] == "failed_pre_connect"


async def test_finalize_cancelled(api_client: AsyncClient, db_session: AsyncSession) -> None:
    """cancelled → cancelled + not_attempted: never dialled."""
    await _seed_call(db_session, call_id="fin-cancelled")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "cancelled"}
    response = await api_client.post(f"{_BASE}/calls/fin-cancelled/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["connection_status"] == "not_attempted"


async def test_finalize_simulation_complete(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """simulation_complete → completed + connected; is_simulation preserved."""
    await _seed_call(db_session, call_id="fin-sim", is_simulation=True)
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "simulation_complete"}
    response = await api_client.post(f"{_BASE}/calls/fin-sim/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["connection_status"] == "connected"
    assert body["is_simulation"] is True


async def test_finalize_simulation_no_answer(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """simulation_no_answer → no_answer + attempted."""
    await _seed_call(db_session, call_id="fin-sim-na", is_simulation=True)
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "simulation_no_answer"}
    response = await api_client.post(f"{_BASE}/calls/fin-sim-na/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_answer"
    assert body["connection_status"] == "attempted"


async def test_finalize_unknown_end_reason_maps_to_failed(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unknown end_reason should fail safely rather than silently completing.
    This is the most conservative safe mapping — unknown states flag for review.
    """
    await _seed_call(db_session, call_id="fin-unknown")
    payload = {"ended_at": "2026-01-01T10:05:00+00:00", "end_reason": "some_future_value"}
    response = await api_client.post(f"{_BASE}/calls/fin-unknown/finalize", json=payload)
    assert response.status_code == 200
    body = response.json()
    # Must NOT be completed — that would silently corrupt analytics
    assert body["status"] != "completed"
    assert body["status"] == "failed"
    assert body["connection_status"] == "failed_pre_connect"


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
    assert second.json()["connection_status"] == "connected"


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
    body = create_resp.json()
    assert body["status"] == "active"
    assert body["is_simulation"] is False

    # 2. Get — active
    get_resp = await api_client.get(f"{_BASE}/calls/{call_id}")
    assert get_resp.status_code == 200
    get_body = get_resp.json()
    assert get_body["status"] == "active"
    assert get_body["connection_status"] == "connected"
    assert get_body["provider_call_id"] == "exo-lifecycle"

    # 3. Finalize
    fin_resp = await api_client.post(
        f"{_BASE}/calls/{call_id}/finalize",
        json={"ended_at": "2026-01-01T10:10:00+00:00", "end_reason": "caller_hangup"},
    )
    assert fin_resp.status_code == 200
    fin_body = fin_resp.json()
    assert fin_body["status"] == "completed"
    assert fin_body["connection_status"] == "connected"

    # 4. Get — completed
    final_get = await api_client.get(f"{_BASE}/calls/{call_id}")
    assert final_get.status_code == 200
    final_body = final_get.json()
    assert final_body["status"] == "completed"
    assert final_body["connection_status"] == "connected"
    assert final_body["ended_at"] is not None
    assert final_body["end_reason"] == "caller_hangup"
