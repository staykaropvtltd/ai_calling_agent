"""
SH-05 — Phone number routing API tests.
Covers: GET /internal/v1/phone-routes/{number}
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import PhoneNumberRoute

pytestmark = pytest.mark.asyncio

_BASE = "/internal/v1"


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_route(
    db: AsyncSession,
    *,
    number: str,
    tenant_id: str = "1",
    agent_id: str = "default",
    provider: str = "exotel",
) -> PhoneNumberRoute:
    route = PhoneNumberRoute(
        number=number,
        tenant_id=tenant_id,
        agent_id=agent_id,
        provider=provider,
    )
    db.add(route)
    await db.commit()
    await db.refresh(route)
    return route


# ── GET /internal/v1/phone-routes/{number} ────────────────────────────────────


async def test_get_phone_route_returns_200_with_correct_fields(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Registered number returns 200 with the correct tenant_id and agent_id."""
    await _seed_route(db_session, number="+917314623519", tenant_id="3", agent_id="default")

    r = await api_client.get(f"{_BASE}/phone-routes/+917314623519")

    assert r.status_code == 200
    body = r.json()
    assert body["tenant_id"] == "3"
    assert body["agent_id"] == "default"
    assert body["provider"] == "exotel"


async def test_get_phone_route_unknown_number_returns_404(api_client: AsyncClient) -> None:
    """Unregistered number returns 404 with an informative detail message."""
    r = await api_client.get(f"{_BASE}/phone-routes/+910000000000")

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


async def test_two_numbers_map_to_different_tenants(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two distinct numbers can map to two distinct tenants."""
    await _seed_route(db_session, number="+911111111111", tenant_id="1", agent_id="default")
    await _seed_route(db_session, number="+912222222222", tenant_id="2", agent_id="default")

    r1 = await api_client.get(f"{_BASE}/phone-routes/+911111111111")
    r2 = await api_client.get(f"{_BASE}/phone-routes/+912222222222")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["tenant_id"] == "1"
    assert r2.json()["tenant_id"] == "2"


async def test_e164_values_treated_as_distinct(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """+917314623519 and 917314623519 are different routing keys — no normalisation."""
    await _seed_route(db_session, number="+917314623519", tenant_id="1", agent_id="default")

    r_with_plus = await api_client.get(f"{_BASE}/phone-routes/+917314623519")
    r_without_plus = await api_client.get(f"{_BASE}/phone-routes/917314623519")

    assert r_with_plus.status_code == 200
    assert r_without_plus.status_code == 404


async def test_duplicate_number_rejected_by_primary_key_constraint(
    db_session: AsyncSession,
) -> None:
    """Inserting the same number twice raises an IntegrityError (PK violation)."""
    await _seed_route(db_session, number="+91dup0000001", tenant_id="1", agent_id="default")

    duplicate = PhoneNumberRoute(
        number="+91dup0000001",
        tenant_id="2",
        agent_id="other",
        provider="exotel",
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


async def test_provider_field_returned_correctly(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The provider field is preserved and returned in the response."""
    await _seed_route(
        db_session,
        number="+917777777777",
        tenant_id="5",
        agent_id="hotel-bot",
        provider="exotel",
    )

    r = await api_client.get(f"{_BASE}/phone-routes/+917777777777")

    assert r.status_code == 200
    assert r.json()["provider"] == "exotel"
    assert r.json()["agent_id"] == "hotel-bot"
