"""
NH-06 — Admin API tests.
Covers: RBAC, client CRUD + soft-delete + pagination + stats,
        user CRUD + soft-delete + pagination, call log read-only,
        auth endpoint, invalid JWT, tenant isolation.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Caller, Client, User

pytestmark = pytest.mark.asyncio

_JWT_SECRET = "test-secret-key-not-for-production-only"
_JWT_ALG = "HS256"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _create_client(db: AsyncSession, *, name="ACME", slug="acme") -> Client:
    client = Client(name=name, slug=slug, plan="starter", status="active")
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return client


async def _create_user(
    db: AsyncSession, *, email="u@example.com", role="agent", tenant_id=None
) -> User:
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


async def test_admin_rejects_non_super_admin_role(api_client: AsyncClient, user_headers: dict):
    r = await api_client.get("/admin/clients", headers=user_headers)
    assert r.status_code == 403
    assert "super_admin" in r.json()["detail"]


async def test_admin_allows_super_admin_role(api_client: AsyncClient, super_admin_headers: dict):
    r = await api_client.get("/admin/clients", headers=super_admin_headers)
    assert r.status_code == 200


async def test_invalid_token_returns_401(api_client: AsyncClient):
    """A malformed JWT must be rejected with 401."""
    r = await api_client.get(
        "/admin/clients",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert r.status_code == 401


async def test_expired_token_returns_401(api_client: AsyncClient):
    """An expired JWT must be rejected with 401."""
    expired = jwt.encode(
        {
            "sub": "test",
            "role": "super_admin",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "type": "access",
        },
        _JWT_SECRET,
        _JWT_ALG,
    )
    r = await api_client.get(
        "/admin/clients",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert r.status_code == 401


async def test_tenant_admin_role_is_rejected_on_all_admin_routes(api_client: AsyncClient):
    """JWT with role=tenant_admin (not super_admin) must receive 403 on every admin route."""
    token = jwt.encode(
        {
            "sub": "ta@example.com",
            "role": "tenant_admin",
            "exp": datetime.now(UTC) + timedelta(minutes=30),
            "type": "access",
        },
        _JWT_SECRET,
        _JWT_ALG,
    )
    headers = {"Authorization": f"Bearer {token}"}
    for method, path in [
        ("GET", "/admin/clients"),
        ("GET", "/admin/users"),
        ("GET", "/admin/calls"),
    ]:
        r = await api_client.request(method, path, headers=headers)
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoint (/auth/login)
# ─────────────────────────────────────────────────────────────────────────────


async def test_auth_login_success(api_client: AsyncClient):
    """POST /auth/login with JSON email/password returns both tokens."""
    r = await api_client.post(
        "/auth/login",
        json={"email": "admin@staykaro.com", "password": "test-admin-password"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_auth_login_wrong_password_401(api_client: AsyncClient):
    """POST /auth/login with wrong password returns 401."""
    r = await api_client.post(
        "/auth/login",
        json={"email": "admin@staykaro.com", "password": "wrong-password"},
    )
    assert r.status_code == 401


async def test_auth_login_wrong_email_401(api_client: AsyncClient):
    """POST /auth/login with unknown email returns 401."""
    r = await api_client.post(
        "/auth/login",
        json={"email": "unknown@example.com", "password": "test-admin-password"},
    )
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /auth/me
# ─────────────────────────────────────────────────────────────────────────────


async def test_auth_me_returns_profile(api_client: AsyncClient, super_admin_headers: dict):
    """GET /auth/me returns the user profile encoded in the JWT."""
    r = await api_client.get("/auth/me", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "super_admin"
    assert "user_id" in body
    assert "email" in body
    assert "permissions" in body
    assert "tenant:write" in body["permissions"]


async def test_auth_me_requires_bearer(api_client: AsyncClient):
    """GET /auth/me without a token returns 401."""
    r = await api_client.get("/auth/me")
    assert r.status_code == 401


async def test_auth_me_rejects_refresh_token(api_client: AsyncClient):
    """Sending a refresh token to GET /auth/me must return 401."""
    login = await api_client.post(
        "/auth/login",
        json={"email": "admin@staykaro.com", "password": "test-admin-password"},
    )
    refresh_token = login.json()["refresh_token"]
    r = await api_client.get("/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /auth/refresh
# ─────────────────────────────────────────────────────────────────────────────


async def test_auth_refresh_issues_new_token_pair(api_client: AsyncClient):
    """POST /auth/refresh with a valid refresh token returns a new token pair."""
    login = await api_client.post(
        "/auth/login",
        json={"email": "admin@staykaro.com", "password": "test-admin-password"},
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    r = await api_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0


async def test_auth_refresh_rejects_access_token(api_client: AsyncClient):
    """Sending an access token to /auth/refresh must be rejected with 401."""
    login = await api_client.post(
        "/auth/login",
        json={"email": "admin@staykaro.com", "password": "test-admin-password"},
    )
    access_token = login.json()["access_token"]
    r = await api_client.post("/auth/refresh", json={"refresh_token": access_token})
    assert r.status_code == 401


async def test_auth_refresh_rejects_invalid_token(api_client: AsyncClient):
    """A malformed token must be rejected with 401."""
    r = await api_client.post("/auth/refresh", json={"refresh_token": "not.a.valid.jwt"})
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# /auth/logout
# ─────────────────────────────────────────────────────────────────────────────


async def test_auth_logout_returns_204(api_client: AsyncClient, super_admin_headers: dict):
    """POST /auth/logout with a valid token returns 204."""
    r = await api_client.post("/auth/logout", headers=super_admin_headers)
    assert r.status_code == 204


async def test_auth_logout_requires_bearer(api_client: AsyncClient):
    """POST /auth/logout without a token returns 401."""
    r = await api_client.post("/auth/logout")
    assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Agent role — /admin/* access
# ─────────────────────────────────────────────────────────────────────────────


async def test_agent_role_is_rejected_on_all_admin_routes(
    api_client: AsyncClient, agent_headers: dict
):
    """JWT with role=agent must receive 403 on every admin route."""
    for method, path in [
        ("GET", "/admin/clients"),
        ("GET", "/admin/users"),
        ("GET", "/admin/calls"),
    ]:
        r = await api_client.request(method, path, headers=agent_headers)
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


async def test_auth_token_endpoint_removed(api_client: AsyncClient):
    """The old /auth/token endpoint must no longer exist (404 or 405)."""
    r = await api_client.post(
        "/auth/token",
        data={"username": "admin", "password": "test-admin-password"},
    )
    assert r.status_code in (404, 405)


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
    r = await api_client.post(
        "/admin/clients", json={"name": "No Slug"}, headers=super_admin_headers
    )
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


async def test_update_client_conflicting_slug_409(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    """Updating a client's slug to one already taken by another client must return 409."""
    c1 = await _create_client(db_session, name="Client One", slug="slug-one")
    c2 = await _create_client(db_session, name="Client Two", slug="slug-two")
    r = await api_client.put(
        f"/admin/clients/{c2.id}",
        json={"slug": c1.slug},
        headers=super_admin_headers,
    )
    assert r.status_code == 409
    assert "Slug already exists" in r.json()["detail"]


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


async def test_create_user_invalid_role_400(api_client: AsyncClient, super_admin_headers: dict):
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
    r = await api_client.post(
        "/admin/users", json={"email": "x@x.com"}, headers=super_admin_headers
    )
    assert r.status_code == 422


async def test_create_user_invalid_tenant_id_404(
    api_client: AsyncClient, super_admin_headers: dict
):
    """Creating a user that references a non-existent client must return 404."""
    r = await api_client.post(
        "/admin/users",
        json={"email": "ghost@x.com", "full_name": "Ghost", "role": "agent", "tenant_id": 99999},
        headers=super_admin_headers,
    )
    assert r.status_code == 404
    assert "Tenant not found" in r.json()["detail"]


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


async def test_user_cannot_access_any_admin_endpoints(api_client: AsyncClient, user_headers: dict):
    """A non-super_admin token must be rejected on every admin route."""
    endpoints = [
        ("GET", "/admin/clients"),
        ("GET", "/admin/users"),
        ("GET", "/admin/calls"),
    ]
    for method, path in endpoints:
        r = await api_client.request(method, path, headers=user_headers)
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# Tenant / client isolation
# ─────────────────────────────────────────────────────────────────────────────


async def test_cross_tenant_user_isolation(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    """Users belonging to tenant A must NOT appear when listing tenant B's users."""
    c1 = await _create_client(db_session, name="Tenant A", slug="tenant-a")
    c2 = await _create_client(db_session, name="Tenant B", slug="tenant-b")
    await _create_user(db_session, email="user-a@example.com", tenant_id=c1.id)
    await _create_user(db_session, email="user-b@example.com", tenant_id=c2.id)

    r = await api_client.get(f"/admin/users?tenant_id={c1.id}", headers=super_admin_headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["data"]]
    assert "user-a@example.com" in emails
    assert "user-b@example.com" not in emails


async def test_cross_tenant_call_isolation(
    api_client: AsyncClient, super_admin_headers: dict, db_session: AsyncSession
):
    """Calls belonging to tenant A must NOT appear when filtering by tenant B."""
    c1 = await _create_client(db_session, name="Hotel A", slug="hotel-a")
    c2 = await _create_client(db_session, name="Hotel B", slug="hotel-b")
    await _create_call(db_session, client_id=c1.id)
    await _create_call(db_session, client_id=c2.id)

    r = await api_client.get(f"/admin/calls?tenant_id={c2.id}", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["client_id"] == c2.id


async def test_cross_tenant_client_not_visible_to_non_super_admin(
    api_client: AsyncClient, db_session: AsyncSession
):
    """A JWT with role=tenant_admin must not be able to enumerate other clients."""
    await _create_client(db_session, name="Secret Client", slug="secret")
    token = jwt.encode(
        {
            "sub": "agent@tenant.com",
            "role": "tenant_admin",
            "exp": datetime.now(UTC) + timedelta(minutes=30),
            "type": "access",
        },
        _JWT_SECRET,
        _JWT_ALG,
    )
    r = await api_client.get(
        "/admin/clients",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# RBAC — tenant_admin scoped access
# ─────────────────────────────────────────────────────────────────────────────


async def test_tenant_admin_rejected_on_client_management_routes(
    api_client: AsyncClient, make_tenant_admin_headers
):
    """tenant_admin must receive 403 on all client-management routes (super_admin only)."""
    headers = make_tenant_admin_headers(client_id=1)
    for method, path in [
        ("GET", "/admin/clients"),
        ("GET", "/admin/clients/1"),
        ("PUT", "/admin/clients/1"),
        ("DELETE", "/admin/clients/1"),
    ]:
        r = await api_client.request(method, path, headers=headers, json={})
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


async def test_tenant_admin_rejected_on_user_mutations(
    api_client: AsyncClient, make_tenant_admin_headers
):
    """tenant_admin must receive 403 on user create/update/delete (super_admin only)."""
    headers = make_tenant_admin_headers(client_id=1)
    for method, path in [
        ("POST", "/admin/users"),
        ("PUT", "/admin/users/some-uuid"),
        ("DELETE", "/admin/users/some-uuid"),
    ]:
        r = await api_client.request(method, path, headers=headers, json={})
        assert r.status_code == 403, f"{method} {path} returned {r.status_code}"


async def test_tenant_admin_can_list_own_users(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin with a client_id JWT claim can list users belonging to their tenant."""
    own_tenant = await _create_client(db_session, name="Own Tenant", slug="own-tenant")
    other_tenant = await _create_client(db_session, name="Other Tenant", slug="other-tenant")
    await _create_user(db_session, email="own@example.com", tenant_id=own_tenant.id)
    await _create_user(db_session, email="other@example.com", tenant_id=other_tenant.id)
    await _create_user(db_session, email="unlinked@example.com")

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get("/admin/users", headers=headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["data"]]
    assert "own@example.com" in emails
    assert "other@example.com" not in emails
    assert "unlinked@example.com" not in emails


async def test_tenant_admin_cannot_escalate_user_list_via_query_param(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """A tenant_admin supplying another tenant's ID as ?tenant_id= MUST NOT see that tenant's data.
    The backend must ignore the query param and always scope to the JWT's client_id.
    """
    own_tenant = await _create_client(db_session, name="Own", slug="own")
    other_tenant = await _create_client(db_session, name="Other", slug="other")
    await _create_user(db_session, email="victim@example.com", tenant_id=other_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    # Attempt to read other tenant's users by injecting their tenant_id in the param
    r = await api_client.get(f"/admin/users?tenant_id={other_tenant.id}", headers=headers)
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()["data"]]
    assert "victim@example.com" not in emails
    assert r.json()["total"] == 0  # own tenant has no users


async def test_tenant_admin_cannot_get_other_tenants_user_by_id(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin cannot fetch a user belonging to a different tenant by ID."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-t")
    other_tenant = await _create_client(db_session, name="Other", slug="other-t")
    victim = await _create_user(db_session, email="victim@example.com", tenant_id=other_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get(f"/admin/users/{victim.id}", headers=headers)
    assert r.status_code == 403


async def test_tenant_admin_can_get_own_user_by_id(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin can fetch a user that belongs to their own tenant by ID."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-u")
    own_user = await _create_user(db_session, email="myuser@example.com", tenant_id=own_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get(f"/admin/users/{own_user.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "myuser@example.com"


async def test_tenant_admin_can_list_own_calls(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin can list calls belonging to their tenant; other tenants' calls are hidden."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-c")
    other_tenant = await _create_client(db_session, name="Other", slug="other-c")
    await _create_call(db_session, client_id=own_tenant.id)
    await _create_call(db_session, client_id=other_tenant.id)
    await _create_call(db_session)  # unlinked call

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get("/admin/calls", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["client_id"] == own_tenant.id


async def test_tenant_admin_cannot_escalate_call_list_via_query_param(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """A tenant_admin supplying another tenant's ID as ?tenant_id= MUST NOT see that tenant's calls."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-ce")
    other_tenant = await _create_client(db_session, name="Other", slug="other-ce")
    await _create_call(db_session, client_id=other_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get(f"/admin/calls?tenant_id={other_tenant.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0  # own tenant has no calls; param was ignored


async def test_tenant_admin_cannot_get_other_tenants_call_by_id(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin cannot fetch a call belonging to a different tenant by ID."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-ci")
    other_tenant = await _create_client(db_session, name="Other", slug="other-ci")
    victim_call = await _create_call(db_session, client_id=other_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get(f"/admin/calls/{victim_call.id}", headers=headers)
    assert r.status_code == 403


async def test_tenant_admin_can_get_own_call_by_id(
    api_client: AsyncClient, db_session: AsyncSession, make_tenant_admin_headers
):
    """tenant_admin can fetch a call that belongs to their own tenant by ID."""
    own_tenant = await _create_client(db_session, name="Own", slug="own-co")
    own_call = await _create_call(db_session, client_id=own_tenant.id)

    headers = make_tenant_admin_headers(client_id=own_tenant.id)
    r = await api_client.get(f"/admin/calls/{own_call.id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == own_call.id
