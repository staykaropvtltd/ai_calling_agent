"""
NH-06 — Admin API tests.
Covers: RBAC, client CRUD + soft-delete + pagination + stats,
        user CRUD + soft-delete + pagination, call log read-only.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Caller, Client, User

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _create_client(db: AsyncSession, *, name="ACME", slug="acme") -> Client:
    client = Client(name=name, slug=slug, plan="starter", status="active")
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def _create_user(db: AsyncSession, *, email="u@example.com", role="agent", tenant_id=None) -> User:
    user = User(email=email, full_name="Test User", role=role, tenant_id=tenant_id)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_call(db: AsyncSession, *, client_id=None) -> Caller:
    call = Caller(
        customer_name="John",
        phone_number="+919876543210",
        hotel_name="Grand Hotel",
        check_in_date="2026-09-01",
        check_out_date="2026-09-05",
        client_id=client_id,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    return call


# ─────────────────────────────────────────────────────────────────────────────
# RBAC
# ─────────────────────────────────────────────────────────────────────────────


async def test_admin_requires_bearer_token(api_client: AsyncClient):
    r = await api_client.get("/admin/clients")
    assert r.status_code == 401


async def test_admin_rejects_non_super_admin_role(
    api_client: AsyncClient, user_headers: dict
):
    r = await api_client.get("/admin/clients", headers=user_headers)
    assert r.status_code == 403
    assert "super_admin" in r.json()["detail"]


async def test_admin_allows_super_admin_role(
    api_client: AsyncClient, super_admin_headers: dict
):
    r = await api_client.get("/admin/clients", headers=super_admin_headers)
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Client CRUD
# ─────────────────────────────────────────────────────────────────────────────


async def test_create_client_success(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.post(
        "/admin/clients",
        json={"name": "ACME Hotels", "slug": "acme-hotels", "plan": "pro"},
        headers=super_admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "acme-hotels"
    assert body["plan"] == "pro"
    assert body["status"] == "active"
    assert body["id"] is not None


async def test_create_client_invalid_plan_400(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.post(
        "/admin/clients",
        json={"name": "X", "slug": "x", "plan": "invalid"},
        headers=super_admin_headers,
    )
    assert r.status_code == 400


async def test_create_client_missing_required_fields_422(
    api_client: AsyncClient, super_admin_headers: dict
):
    r = await api_client.post("/admin/clients", json={"name": "No Slug"}, headers=super_admin_headers)
    assert r.status_code == 422


async def test_create_client_duplicate_slug_409(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    await _create_client(db_session, slug="dupe")
    r = await api_client.post(
        "/admin/clients",
        json={"name": "Another", "slug": "dupe"},
        headers=super_admin_headers,
    )
    assert r.status_code == 409
    assert "Slug already exists" in r.json()["detail"]


async def test_list_clients_empty(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/clients", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == []
    assert body["total"] == 0
    assert body["total_pages"] == 0


async def test_list_clients_pagination(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    for i in range(5):
        await _create_client(db_session, name=f"Client {i}", slug=f"client-{i}")

    r = await api_client.get("/admin/clients?page=1&per_page=2", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert body["total"] == 5
    assert body["total_pages"] == 3
    assert body["page"] == 1
    assert body["per_page"] == 2


async def test_list_clients_filter_by_status(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    await _create_client(db_session, slug="active-1")
    inactive = Client(name="Gone", slug="gone", status="inactive")
    db_session.add(inactive)
    await db_session.commit()

    r = await api_client.get("/admin/clients?status=active", headers=super_admin_headers)
    assert r.status_code == 200
    slugs = [c["slug"] for c in r.json()["data"]]
    assert "active-1" in slugs
    assert "gone" not in slugs


async def test_get_client_found(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    r = await api_client.get(f"/admin/clients/{client.id}", headers=super_admin_headers)
    assert r.status_code == 200
    assert r.json()["id"] == client.id


async def test_get_client_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/clients/99999", headers=super_admin_headers)
    assert r.status_code == 404


async def test_update_client_success(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    r = await api_client.put(
        f"/admin/clients/{client.id}",
        json={"name": "ACME Hotels Updated", "plan": "enterprise"},
        headers=super_admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "ACME Hotels Updated"
    assert r.json()["plan"] == "enterprise"


async def test_update_client_invalid_status_400(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    r = await api_client.put(
        f"/admin/clients/{client.id}",
        json={"status": "deleted"},
        headers=super_admin_headers,
    )
    assert r.status_code == 400


async def test_update_client_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.put(
        "/admin/clients/99999", json={"name": "X"}, headers=super_admin_headers
    )
    assert r.status_code == 404


async def test_delete_client_is_soft_not_hard(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    """DELETE must set status=inactive, not remove the row."""
    client = await _create_client(db_session)
    client_id = client.id

    r = await api_client.delete(f"/admin/clients/{client_id}", headers=super_admin_headers)
    assert r.status_code == 204

    # Row must still exist in the database
    still_there = await db_session.get(Client, client_id)
    assert still_there is not None
    assert still_there.status == "inactive"


async def test_delete_client_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.delete("/admin/clients/99999", headers=super_admin_headers)
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Client stats
# ─────────────────────────────────────────────────────────────────────────────


async def test_client_stats_empty(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    r = await api_client.get(f"/admin/clients/{client.id}/stats", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["client_id"] == client.id
    assert body["total_calls"] == 0
    assert body["calls_this_month"] == 0
    assert body["active_users"] == 0


async def test_client_stats_with_calls_and_users(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    await _create_call(db_session, client_id=client.id)
    await _create_call(db_session, client_id=client.id)
    await _create_user(db_session, email="u1@x.com", tenant_id=client.id)

    r = await api_client.get(f"/admin/clients/{client.id}/stats", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total_calls"] == 2
    assert body["active_users"] == 1


async def test_client_stats_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/clients/99999/stats", headers=super_admin_headers)
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────────────────────────────────────


async def test_create_user_success(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    r = await api_client.post(
        "/admin/users",
        json={
            "email": "new@example.com",
            "full_name": "New User",
            "role": "tenant_admin",
            "tenant_id": client.id,
        },
        headers=super_admin_headers,
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "tenant_admin"
    assert body["status"] == "active"
    assert body["id"] is not None


async def test_create_user_invalid_role_400(
    api_client: AsyncClient, super_admin_headers: dict
):
    r = await api_client.post(
        "/admin/users",
        json={"email": "x@x.com", "full_name": "X", "role": "owner"},
        headers=super_admin_headers,
    )
    assert r.status_code == 400


async def test_create_user_duplicate_email_409(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    await _create_user(db_session, email="dupe@example.com")
    r = await api_client.post(
        "/admin/users",
        json={"email": "dupe@example.com", "full_name": "Dup"},
        headers=super_admin_headers,
    )
    assert r.status_code == 409


async def test_create_user_missing_required_fields_422(
    api_client: AsyncClient, super_admin_headers: dict
):
    r = await api_client.post("/admin/users", json={"email": "x@x.com"}, headers=super_admin_headers)
    assert r.status_code == 422


async def test_list_users_pagination(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    for i in range(4):
        await _create_user(db_session, email=f"u{i}@x.com")

    r = await api_client.get("/admin/users?page=1&per_page=2", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) == 2
    assert body["total"] == 4
    assert body["total_pages"] == 2


async def test_list_users_filter_by_tenant(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    c1 = await _create_client(db_session, slug="c1")
    c2 = await _create_client(db_session, name="C2", slug="c2")
    await _create_user(db_session, email="a@x.com", tenant_id=c1.id)
    await _create_user(db_session, email="b@x.com", tenant_id=c2.id)

    r = await api_client.get(f"/admin/users?tenant_id={c1.id}", headers=super_admin_headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["data"]]
    assert "a@x.com" in emails
    assert "b@x.com" not in emails


async def test_get_user_found(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    user = await _create_user(db_session)
    r = await api_client.get(f"/admin/users/{user.id}", headers=super_admin_headers)
    assert r.status_code == 200
    assert r.json()["email"] == user.email


async def test_get_user_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/users/no-such-uuid", headers=super_admin_headers)
    assert r.status_code == 404


async def test_update_user_success(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    user = await _create_user(db_session)
    r = await api_client.put(
        f"/admin/users/{user.id}",
        json={"full_name": "Updated Name", "role": "tenant_admin"},
        headers=super_admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "Updated Name"
    assert r.json()["role"] == "tenant_admin"


async def test_delete_user_is_soft_not_hard(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    """DELETE must set status=suspended, not remove the row."""
    user = await _create_user(db_session)
    user_id = user.id

    r = await api_client.delete(f"/admin/users/{user_id}", headers=super_admin_headers)
    assert r.status_code == 204

    still_there = await db_session.get(User, user_id)
    assert still_there is not None
    assert still_there.status == "suspended"


async def test_delete_user_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.delete("/admin/users/no-such-uuid", headers=super_admin_headers)
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Call log (read-only)
# ─────────────────────────────────────────────────────────────────────────────


async def test_list_calls_empty(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/calls", headers=super_admin_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0


async def test_list_calls_with_data(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    for _ in range(3):
        await _create_call(db_session)

    r = await api_client.get("/admin/calls?per_page=2", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["data"]) == 2
    assert body["total_pages"] == 2


async def test_list_calls_filter_by_tenant(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    client = await _create_client(db_session)
    await _create_call(db_session, client_id=client.id)
    await _create_call(db_session)  # no client

    r = await api_client.get(f"/admin/calls?tenant_id={client.id}", headers=super_admin_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1


async def test_get_call_found(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    call = await _create_call(db_session)
    r = await api_client.get(f"/admin/calls/{call.id}", headers=super_admin_headers)
    assert r.status_code == 200
    assert r.json()["id"] == call.id


async def test_get_call_not_found_404(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/calls/99999", headers=super_admin_headers)
    assert r.status_code == 404


async def test_call_log_is_read_only(api_client: AsyncClient, super_admin_headers: dict):
    """No POST/PUT/DELETE endpoints should exist on /admin/calls."""
    r_post = await api_client.post("/admin/calls", json={}, headers=super_admin_headers)
    r_put = await api_client.put("/admin/calls/1", json={}, headers=super_admin_headers)
    r_del = await api_client.delete("/admin/calls/1", headers=super_admin_headers)
    assert r_post.status_code == 405
    assert r_put.status_code == 405
    assert r_del.status_code == 405


# ─────────────────────────────────────────────────────────────────────────────
# Tenant isolation (safety rules from contract)
# ─────────────────────────────────────────────────────────────────────────────


async def test_user_cannot_access_any_admin_endpoints(
    api_client: AsyncClient, user_headers: dict
):
    """A non-super_admin token must be rejected on every admin route."""
    endpoints = [
        ("GET", "/admin/clients"),
        ("GET", "/admin/users"),
        ("GET", "/admin/calls"),
    ]
    for method, path in endpoints:
        r = await api_client.request(method, path, headers=user_headers)
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"
