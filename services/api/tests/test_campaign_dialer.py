"""Tests for the outbound campaign calling pipeline.

Covers:
- Campaign start → queues Caller + CallJob records for each eligible contact
- Duplicate prevention (contacts already in dialing state are not re-queued)
- finalize_call cascade → Caller + CampaignContact + Campaign counters updated
- Campaign auto-completes when all contacts are terminal
- New internal endpoints: by-provider-id lookup, call-requests/{id}/dialed
- Retry-eligible contacts queued on campaign resume
- Tenant isolation (cross-tenant access returns 404)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Call, Caller, Campaign, CampaignContact, Client, Customer

pytestmark = pytest.mark.asyncio

_BASE_INT = "/internal/v1"
_T0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
INTERNAL_TOKEN = "test-internal-api-token-not-for-production"


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_client(db: AsyncSession, *, client_id: int = 1, name: str = "Hotel A") -> Client:
    c = Client(id=client_id, name=name)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _seed_customer(db: AsyncSession, *, client_id: int, phone: str = "+917001234567") -> Customer:
    cust = Customer(
        client_id=client_id,
        phone=phone,
        name="Test Guest",
    )
    db.add(cust)
    await db.commit()
    await db.refresh(cust)
    return cust


async def _seed_campaign(
    db: AsyncSession,
    *,
    client_id: int,
    status: str = "draft",
    max_retries: int = 2,
    total_contacts: int = 0,
) -> Campaign:
    camp = Campaign(
        client_id=client_id,
        name="Test Campaign",
        status=status,
        max_retries=max_retries,
        retry_delay_minutes=60,
        total_contacts=total_contacts,
    )
    db.add(camp)
    await db.commit()
    await db.refresh(camp)
    return camp


async def _seed_contact(
    db: AsyncSession,
    *,
    campaign_id: str,
    customer_id: str,
    status: str = "queued",
    attempts: int = 0,
    call_request_id: int | None = None,
) -> CampaignContact:
    cc = CampaignContact(
        campaign_id=campaign_id,
        customer_id=customer_id,
        status=status,
        attempts=attempts,
        call_request_id=call_request_id,
    )
    db.add(cc)
    await db.commit()
    await db.refresh(cc)
    return cc


async def _seed_caller(
    db: AsyncSession,
    *,
    client_id: int,
    phone_number: str = "+917001234567",
    status: str = "queued",
    is_simulation: bool = False,
    telephony_call_id: str | None = None,
) -> Caller:
    caller = Caller(
        client_id=client_id,
        phone_number=phone_number,
        status=status,
        call_type="outbound",
        is_simulation=is_simulation,
        telephony_call_id=telephony_call_id,
    )
    db.add(caller)
    await db.commit()
    await db.refresh(caller)
    return caller


async def _seed_call(
    db: AsyncSession,
    *,
    call_id: str = "call-001",
    tenant_id: str = "1",
    provider_call_id: str | None = None,
    call_request_id: int | None = None,
    connection_status: str = "not_attempted",
    is_simulation: bool = False,
    status: str = "active",
) -> Call:
    call = Call(
        call_id=call_id,
        tenant_id=tenant_id,
        agent_id="campaign-dialer",
        provider_call_id=provider_call_id,
        started_at=_T0,
        status=status,
        connection_status=connection_status,
        is_simulation=is_simulation,
        call_request_id=call_request_id,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


def _tenant_admin_headers(client_id: int, make_headers) -> dict:
    return make_headers(client_id)


# ── Campaign start → queue contacts ──────────────────────────────────────────


async def test_campaign_start_queues_fresh_contacts(
    api_client: AsyncClient,
    db_session: AsyncSession,
    make_tenant_admin_headers,
) -> None:
    """Starting a draft campaign creates Caller + CallJob records for each contact."""
    client = await _seed_client(db_session)
    cust1 = await _seed_customer(db_session, client_id=client.id, phone="+917001111111")
    cust2 = await _seed_customer(db_session, client_id=client.id, phone="+917002222222")
    camp = await _seed_campaign(db_session, client_id=client.id, total_contacts=2)
    await _seed_contact(db_session, campaign_id=camp.id, customer_id=cust1.id)
    await _seed_contact(db_session, campaign_id=camp.id, customer_id=cust2.id)

    headers = make_tenant_admin_headers(client.id)
    r = await api_client.put(
        f"/client/campaigns/{camp.id}",
        json={"status": "running"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["queued_count"] == 2


async def test_campaign_start_skips_already_dialing_contacts(
    api_client: AsyncClient,
    db_session: AsyncSession,
    make_tenant_admin_headers,
) -> None:
    """Contacts that already have a call_request_id (in progress) are not re-queued."""
    client = await _seed_client(db_session)
    cust = await _seed_customer(db_session, client_id=client.id)
    camp = await _seed_campaign(db_session, client_id=client.id, total_contacts=1)
    existing_caller = await _seed_caller(db_session, client_id=client.id, status="dialing")
    await _seed_contact(
        db_session,
        campaign_id=camp.id,
        customer_id=cust.id,
        status="dialing",
        call_request_id=existing_caller.id,
    )

    headers = make_tenant_admin_headers(client.id)
    r = await api_client.put(
        f"/client/campaigns/{camp.id}",
        json={"status": "running"},
        headers=headers,
    )
    assert r.status_code == 200
    # Already-dialing contact must NOT produce an extra queued count
    assert r.json()["queued_count"] == 0


async def test_campaign_start_queues_retry_eligible_contacts(
    api_client: AsyncClient,
    db_session: AsyncSession,
    make_tenant_admin_headers,
) -> None:
    """Contacts with no_answer/failed status and remaining retries are re-queued."""
    client = await _seed_client(db_session)
    cust = await _seed_customer(db_session, client_id=client.id)
    camp = await _seed_campaign(db_session, client_id=client.id, total_contacts=1, max_retries=2)
    old_caller = await _seed_caller(db_session, client_id=client.id, status="no_answer")
    await _seed_contact(
        db_session,
        campaign_id=camp.id,
        customer_id=cust.id,
        status="no_answer",
        attempts=1,  # < max_retries=2
        call_request_id=old_caller.id,
    )

    headers = make_tenant_admin_headers(client.id)
    r = await api_client.put(
        f"/client/campaigns/{camp.id}",
        json={"status": "running"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["queued_count"] == 1


async def test_campaign_start_cross_tenant_returns_404(
    api_client: AsyncClient,
    db_session: AsyncSession,
    make_tenant_admin_headers,
) -> None:
    """A tenant_admin cannot start another tenant's campaign."""
    client_a = await _seed_client(db_session, client_id=1, name="Hotel A")
    client_b = await _seed_client(db_session, client_id=2, name="Hotel B")
    camp_b = await _seed_campaign(db_session, client_id=client_b.id)

    headers_a = make_tenant_admin_headers(client_a.id)
    r = await api_client.put(
        f"/client/campaigns/{camp_b.id}",
        json={"status": "running"},
        headers=headers_a,
    )
    assert r.status_code == 404


# ── Internal API: finalize_call cascade ──────────────────────────────────────


async def test_finalize_call_updates_caller_on_completed(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """finalize_call with caller_hangup cascades: Caller → completed, connected."""
    client = await _seed_client(db_session)
    caller = await _seed_caller(db_session, client_id=client.id, status="dialing")
    call = await _seed_call(
        db_session,
        call_id="c-finalize-1",
        tenant_id=str(client.id),
        call_request_id=caller.id,
        connection_status="not_attempted",
    )

    r = await api_client.post(
        f"{_BASE_INT}/calls/{call.call_id}/finalize",
        json={"ended_at": "2026-01-01T11:00:00+00:00", "end_reason": "caller_hangup"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["connection_status"] == "connected"

    await db_session.refresh(caller)
    assert caller.status == "completed"
    assert caller.connection_status == "connected"
    assert caller.failure_reason is None


async def test_finalize_call_updates_caller_on_no_answer(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    client = await _seed_client(db_session)
    caller = await _seed_caller(db_session, client_id=client.id, status="dialing")
    call = await _seed_call(
        db_session,
        call_id="c-noanswer",
        tenant_id=str(client.id),
        call_request_id=caller.id,
    )

    r = await api_client.post(
        f"{_BASE_INT}/calls/{call.call_id}/finalize",
        json={"ended_at": "2026-01-01T11:00:00+00:00", "end_reason": "no_answer"},
    )
    assert r.status_code == 200
    await db_session.refresh(caller)
    assert caller.status == "no_answer"
    assert caller.failure_reason == "no_answer"


async def test_finalize_call_updates_campaign_counters(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """finalize_call decrements queued_count and increments completed_count."""
    client = await _seed_client(db_session)
    cust = await _seed_customer(db_session, client_id=client.id)
    camp = await _seed_campaign(
        db_session, client_id=client.id, total_contacts=1, status="running"
    )
    camp.queued_count = 1
    await db_session.commit()

    caller = await _seed_caller(db_session, client_id=client.id, status="dialing")
    await _seed_contact(
        db_session,
        campaign_id=camp.id,
        customer_id=cust.id,
        status="dialing",
        call_request_id=caller.id,
    )
    call = await _seed_call(
        db_session,
        call_id="c-counters",
        tenant_id=str(client.id),
        call_request_id=caller.id,
    )

    await api_client.post(
        f"{_BASE_INT}/calls/{call.call_id}/finalize",
        json={"ended_at": "2026-01-01T11:00:00+00:00", "end_reason": "caller_hangup"},
    )

    await db_session.refresh(camp)
    assert camp.queued_count == 0
    assert camp.completed_count == 1
    assert camp.failed_count == 0


async def test_campaign_auto_completes_when_all_contacts_done(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Campaign transitions to 'completed' automatically when queued_count reaches 0."""
    client = await _seed_client(db_session)
    cust = await _seed_customer(db_session, client_id=client.id)
    camp = await _seed_campaign(
        db_session, client_id=client.id, total_contacts=1, status="running"
    )
    camp.queued_count = 1
    await db_session.commit()

    caller = await _seed_caller(db_session, client_id=client.id, status="dialing")
    await _seed_contact(
        db_session,
        campaign_id=camp.id,
        customer_id=cust.id,
        status="dialing",
        call_request_id=caller.id,
    )
    call = await _seed_call(
        db_session,
        call_id="c-autocomplete",
        tenant_id=str(client.id),
        call_request_id=caller.id,
    )

    await api_client.post(
        f"{_BASE_INT}/calls/{call.call_id}/finalize",
        json={"ended_at": "2026-01-01T11:00:00+00:00", "end_reason": "caller_hangup"},
    )

    await db_session.refresh(camp)
    assert camp.status == "completed"


# ── Internal API: new endpoints ───────────────────────────────────────────────


async def test_mark_caller_dialed(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """PATCH /internal/v1/call-requests/{id}/dialed marks caller as dialing."""
    client = await _seed_client(db_session)
    caller = await _seed_caller(db_session, client_id=client.id, status="queued")

    r = await api_client.patch(
        f"{_BASE_INT}/call-requests/{caller.id}/dialed",
        json={"telephony_call_id": "call-uuid-abc", "is_simulation": True},
    )
    assert r.status_code == 200
    await db_session.refresh(caller)
    assert caller.status == "dialing"
    assert caller.telephony_call_id == "call-uuid-abc"
    assert caller.is_simulation is True


async def test_mark_caller_dialed_not_found(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    r = await api_client.patch(
        f"{_BASE_INT}/call-requests/99999/dialed",
        json={"telephony_call_id": "call-uuid-abc"},
    )
    assert r.status_code == 404


async def test_get_call_by_provider_id(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /internal/v1/calls/by-provider/{id} resolves a Call by provider CallSid."""
    await _seed_call(
        db_session,
        call_id="c-byprovider",
        tenant_id="1",
        provider_call_id="exotel-callsid-xyz",
    )

    r = await api_client.get(f"{_BASE_INT}/calls/by-provider/exotel-callsid-xyz")
    assert r.status_code == 200
    assert r.json()["call_id"] == "c-byprovider"
    assert r.json()["provider_call_id"] == "exotel-callsid-xyz"


async def test_get_call_by_provider_id_not_found(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    r = await api_client.get(f"{_BASE_INT}/calls/by-provider/unknown-sid")
    assert r.status_code == 404


# ── create_call with outbound fields ─────────────────────────────────────────


async def test_create_call_with_outbound_fields(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /internal/v1/calls accepts connection_status + call_request_id."""
    client = await _seed_client(db_session)
    caller = await _seed_caller(db_session, client_id=client.id)

    r = await api_client.post(
        f"{_BASE_INT}/calls",
        json={
            "call_id": "outbound-001",
            "tenant_id": str(client.id),
            "agent_id": "campaign-dialer",
            "started_at": "2026-01-01T10:00:00+00:00",
            "provider_call_id": "exotel-sid-001",
            "is_simulation": False,
            "connection_status": "not_attempted",
            "call_request_id": caller.id,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["call_id"] == "outbound-001"

    call = await db_session.get(Call, "outbound-001")
    assert call is not None
    assert call.connection_status == "not_attempted"
    assert call.call_request_id == caller.id


# ── Simulation flag preserved through finalize ────────────────────────────────


async def test_simulation_call_finalize_updates_caller_with_is_simulation(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Simulation calls finalize correctly and Caller.is_simulation stays True."""
    client = await _seed_client(db_session)
    caller = await _seed_caller(
        db_session, client_id=client.id, status="dialing", is_simulation=True
    )
    call = await _seed_call(
        db_session,
        call_id="c-sim",
        tenant_id=str(client.id),
        is_simulation=True,
        call_request_id=caller.id,
    )

    r = await api_client.post(
        f"{_BASE_INT}/calls/{call.call_id}/finalize",
        json={"ended_at": "2026-01-01T11:00:00+00:00", "end_reason": "simulation_complete"},
    )
    assert r.status_code == 200
    assert r.json()["is_simulation"] is True

    await db_session.refresh(caller)
    assert caller.status == "completed"
    assert caller.is_simulation is True
