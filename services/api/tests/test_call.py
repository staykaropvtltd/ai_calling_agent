"""
POST /call — regression coverage for the client_id/tenant-scoping fix.

Against a real Postgres, call_requests' RLS policy (NK-07,
alembic/versions/df467b3bdd3f_*) rejects an INSERT with client_id left NULL
under a tenant_admin/agent's own tenant context — the in-memory SQLite this
suite runs against has no RLS to enforce that, so it can't catch the 500
itself (see tests/test_tenant_isolation.py for the real-Postgres RLS check).
What it can and does verify: the endpoint now stamps client_id from the
caller's JWT, which is the actual fix — a super_admin token (no client_id)
still working confirms the column stays nullable for the cross-tenant case.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Caller

pytestmark = pytest.mark.asyncio

_JWT_SECRET = "test-secret-key-not-for-production-only"
_JWT_ALG = "HS256"

_PAYLOAD = {
    "customer_name": "Raj Kumar",
    "phone_number": "+919876543210",
    "hotel_name": "Taj Palace",
    "check_in_date": "2026-09-15",
    "check_out_date": "2026-09-17",
}


async def test_call_stamps_client_id_from_tenant_admin_token(
    api_client: AsyncClient,
    db_session: AsyncSession,
    make_tenant_admin_headers,
):
    resp = await api_client.post("/call", json=_PAYLOAD, headers=make_tenant_admin_headers(5))
    assert resp.status_code == 200

    caller = (await db_session.execute(select(Caller))).scalar_one()
    assert caller.client_id == 5


async def test_call_allows_null_client_id_for_super_admin_token(
    api_client: AsyncClient,
    db_session: AsyncSession,
    super_admin_headers: dict,
):
    resp = await api_client.post("/call", json=_PAYLOAD, headers=super_admin_headers)
    assert resp.status_code == 200

    caller = (await db_session.execute(select(Caller))).scalar_one()
    assert caller.client_id is None


async def test_call_stamps_client_id_from_agent_token(
    api_client: AsyncClient,
    db_session: AsyncSession,
):
    expire = datetime.now(UTC) + timedelta(minutes=30)
    token = jwt.encode(
        {
            "sub": "agent@test.com",
            "role": "agent",
            "client_id": 7,
            "exp": expire,
            "type": "access",
        },
        _JWT_SECRET,
        _JWT_ALG,
    )
    resp = await api_client.post(
        "/call", json=_PAYLOAD, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200

    caller = (await db_session.execute(select(Caller))).scalar_one()
    assert caller.client_id == 7
