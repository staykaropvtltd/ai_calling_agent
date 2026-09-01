"""
Phase 1 — Customer entity tests.
Covers: CRUD, upsert-by-phone, search, pagination, tenant isolation, RBAC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Client

pytestmark = pytest.mark.asyncio

_JWT_SECRET = "test-secret-key-not-for-production-only"
_JWT_ALG = "HS256"
_BASE = "/client/customers"


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _create_client(db: AsyncSession, *, name: str = "Test Hotel") -> Client:
    c = Client(
        name=name,
        slug=name.lower().replace(" ", "-"),
        plan="starter",
        status="active",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


def _token(role: str, client_id: int | None = None) -> str:
    payload: dict = {
        "sub": f"{role}@test.com",
        "role": role,
        "exp": datetime.now(UTC) + timedelta(minutes=30),
        "type": "access",
    }
    if client_id is not None:
        payload["client_id"] = client_id
    return jwt.encode(payload, _JWT_SECRET, _JWT_ALG)


def _headers(role: str, client_id: int | None = None) -> dict:
    return {"Authorization": f"Bearer {_token(role, client_id)}"}


_NEW_CUSTOMER = {
    "name": "Nihal Talla",
    "phone": "+971501234567",
    "email": "nihal@example.com",
    "language_code": "en",
    "timezone": "Asia/Dubai",
    "country_code": "AE",
}


# ── POST /client/customers ────────────────────────────────────────────────────


async def test_create_customer_returns_201(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    response = await api_client.post(
        _BASE, json=_NEW_CUSTOMER, headers=_headers("tenant_admin", client.id)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["phone"] == "+971501234567"
    assert body["name"] == "Nihal Talla"
    assert body["client_id"] == client.id
    assert "id" in body


async def test_create_customer_agent_allowed(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Agents can create customers — _require_client allows both tenant_admin and agent."""
    client = await _create_client(db_session)
    response = await api_client.post(
        _BASE,
        json={"name": "Agent Created", "phone": "+971509999999"},
        headers=_headers("agent", client.id),
    )
    assert response.status_code == 201


async def test_create_customer_super_admin_blocked(api_client: AsyncClient) -> None:
    """super_admin has no client account — must be rejected with 403."""
    response = await api_client.post(
        _BASE, json=_NEW_CUSTOMER, headers=_headers("super_admin")
    )
    assert response.status_code == 403


async def test_create_customer_unauthenticated_blocked(api_client: AsyncClient) -> None:
    response = await api_client.post(_BASE, json=_NEW_CUSTOMER)
    assert response.status_code == 401


async def test_create_customer_missing_phone_returns_422(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    response = await api_client.post(
        _BASE, json={"name": "No Phone"}, headers=_headers("tenant_admin", client.id)
    )
    assert response.status_code == 422


# ── Upsert by phone ───────────────────────────────────────────────────────────


async def test_upsert_by_phone_updates_existing(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """POST with a phone number that already exists for this tenant should
    update the existing record rather than returning 409.
    This is the upsert-by-phone contract (see unique index uq_customers_client_phone).
    """
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    first = await api_client.post(_BASE, json={"phone": "+971501111111", "name": "First Name"}, headers=h)
    assert first.status_code == 201
    first_id = first.json()["id"]

    # Same phone, different name → should update existing, return 201
    second = await api_client.post(
        _BASE,
        json={"phone": "+971501111111", "name": "Updated Name", "email": "new@example.com"},
        headers=h,
    )
    assert second.status_code == 201
    second_body = second.json()
    # Must be the same record
    assert second_body["id"] == first_id
    assert second_body["name"] == "Updated Name"
    assert second_body["email"] == "new@example.com"
    assert second_body["phone"] == "+971501111111"


async def test_upsert_different_phone_creates_new_record(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Different phone numbers in the same tenant create separate customers."""
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    first = await api_client.post(_BASE, json={"phone": "+971502222222"}, headers=h)
    second = await api_client.post(_BASE, json={"phone": "+971503333333"}, headers=h)
    assert first.json()["id"] != second.json()["id"]


# ── GET /client/customers ─────────────────────────────────────────────────────


async def test_list_customers_empty(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    response = await api_client.get(_BASE, headers=_headers("tenant_admin", client.id))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["data"] == []


async def test_list_customers_pagination(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    for i in range(5):
        await api_client.post(_BASE, json={"phone": f"+9715012345{i:02d}", "name": f"Guest {i}"}, headers=h)

    page1 = await api_client.get(_BASE, params={"per_page": 3}, headers=h)
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 5
    assert len(body1["data"]) == 3
    assert body1["total_pages"] == 2

    page2 = await api_client.get(_BASE, params={"per_page": 3, "page": 2}, headers=h)
    assert len(page2.json()["data"]) == 2


async def test_list_customers_search(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    await api_client.post(_BASE, json={"phone": "+971500000001", "name": "Alice Smith"}, headers=h)
    await api_client.post(_BASE, json={"phone": "+971500000002", "name": "Bob Jones"}, headers=h)

    r = await api_client.get(_BASE, params={"search": "alice"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["name"] == "Alice Smith"


# ── GET /client/customers/{customer_id} ──────────────────────────────────────


async def test_get_customer_by_id(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    created = await api_client.post(_BASE, json=_NEW_CUSTOMER, headers=h)
    customer_id = created.json()["id"]

    r = await api_client.get(f"{_BASE}/{customer_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == customer_id
    assert r.json()["phone"] == "+971501234567"


async def test_get_customer_not_found(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    r = await api_client.get(
        f"{_BASE}/00000000-0000-0000-0000-000000000000",
        headers=_headers("tenant_admin", client.id),
    )
    assert r.status_code == 404


# ── PUT /client/customers/{customer_id} ──────────────────────────────────────


async def test_update_customer(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    h = _headers("tenant_admin", client.id)

    created = (await api_client.post(_BASE, json={"phone": "+971504444444", "name": "Old Name"}, headers=h)).json()
    customer_id = created["id"]

    r = await api_client.put(
        f"{_BASE}/{customer_id}",
        json={"name": "New Name", "notes": "VIP guest"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "New Name"
    assert body["notes"] == "VIP guest"
    # phone is immutable — not in PUT schema, should be unchanged
    assert body["phone"] == "+971504444444"


async def test_update_customer_not_found(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client = await _create_client(db_session)
    r = await api_client.put(
        f"{_BASE}/00000000-0000-0000-0000-000000000000",
        json={"name": "X"},
        headers=_headers("tenant_admin", client.id),
    )
    assert r.status_code == 404


# ── Tenant isolation ─────────────────────────────────────────────────────────


async def test_list_only_returns_own_tenant_customers(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """GET /client/customers must only return rows for the JWT's tenant.
    The application-level WHERE client_id == X filter enforces this in SQLite
    unit tests; PostgreSQL RLS provides the second independent layer in prod.
    """
    client_a = await _create_client(db_session, name="Hotel Alpha")
    client_b = await _create_client(db_session, name="Hotel Beta")

    ha = _headers("tenant_admin", client_a.id)
    hb = _headers("tenant_admin", client_b.id)

    # Create one customer under each tenant
    await api_client.post(_BASE, json={"phone": "+971511111111", "name": "Alpha Guest"}, headers=ha)
    await api_client.post(_BASE, json={"phone": "+971522222222", "name": "Beta Guest"}, headers=hb)

    # Client A sees only their customer
    r_a = await api_client.get(_BASE, headers=ha)
    assert r_a.json()["total"] == 1
    assert r_a.json()["data"][0]["name"] == "Alpha Guest"

    # Client B sees only their customer
    r_b = await api_client.get(_BASE, headers=hb)
    assert r_b.json()["total"] == 1
    assert r_b.json()["data"][0]["name"] == "Beta Guest"


async def test_get_by_id_returns_404_for_other_tenant(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Explicit client_id check prevents information-leakage via 403 timing
    distinction — wrong-tenant access returns 404, not 403.
    """
    client_a = await _create_client(db_session, name="Hotel Alpha")
    client_b = await _create_client(db_session, name="Hotel Beta")

    ha = _headers("tenant_admin", client_a.id)
    hb = _headers("tenant_admin", client_b.id)

    # Client A creates a customer
    created = (await api_client.post(_BASE, json={"phone": "+971511111111"}, headers=ha)).json()
    customer_id = created["id"]

    # Client B tries to access Client A's customer — must get 404, not 403
    r = await api_client.get(f"{_BASE}/{customer_id}", headers=hb)
    assert r.status_code == 404


async def test_update_by_id_returns_404_for_other_tenant(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    client_a = await _create_client(db_session, name="Hotel Alpha")
    client_b = await _create_client(db_session, name="Hotel Beta")

    ha = _headers("tenant_admin", client_a.id)
    hb = _headers("tenant_admin", client_b.id)

    created = (await api_client.post(_BASE, json={"phone": "+971511111112"}, headers=ha)).json()
    customer_id = created["id"]

    r = await api_client.put(f"{_BASE}/{customer_id}", json={"name": "Hijacked"}, headers=hb)
    assert r.status_code == 404


async def test_same_phone_different_tenants_creates_separate_records(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The uniqueness constraint is (client_id, phone), not just phone.
    The same phone number can belong to different tenants.
    """
    client_a = await _create_client(db_session, name="Hotel Alpha")
    client_b = await _create_client(db_session, name="Hotel Beta")

    shared_phone = "+971500000099"

    r_a = await api_client.post(
        _BASE, json={"phone": shared_phone, "name": "Guest A"}, headers=_headers("tenant_admin", client_a.id)
    )
    r_b = await api_client.post(
        _BASE, json={"phone": shared_phone, "name": "Guest B"}, headers=_headers("tenant_admin", client_b.id)
    )

    assert r_a.status_code == 201
    assert r_b.status_code == 201
    # Different records despite same phone
    assert r_a.json()["id"] != r_b.json()["id"]
    assert r_a.json()["name"] == "Guest A"
    assert r_b.json()["name"] == "Guest B"
