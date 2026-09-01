"""
NK-06 — RBAC role matrix.

Execution Plan ticket NK-06 ("Done when: Role matrix passes") and Testing
Guide §6 ("An expired or tampered JWT is rejected on every protected
endpoint, not just some"). Prior to this file, role enforcement was proven
piecemeal — one or two example routes per test in test_admin.py. This file
is the single, exhaustive table: every /admin/* route (plus the
non-admin-gated /call and /auth/me, /auth/logout) crossed against every
role this system has (unauthenticated, agent, tenant_admin, super_admin),
asserting the exact expected outcome for each cell.

Deliberately checks *category* of outcome (401 unauthenticated / 403
wrong-role / "got past the gate") rather than exact success bodies —
per-endpoint business-logic correctness (404s, payload shapes, pagination)
is already covered where each endpoint is defined in test_admin.py. This
file's only job is: did the right roles get in, and did the wrong roles
get rejected, everywhere, at once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt

pytestmark = pytest.mark.asyncio

_JWT_SECRET = "test-secret-key-not-for-production-only"
_JWT_ALG = "HS256"

# (method, path, json body or None, roles allowed past the gate)
# "allowed past the gate" means: not rejected by the RBAC dependency itself.
# Downstream 404s (resource "1"/"x" not existing in a fresh test DB) are
# expected and irrelevant here — this file only asserts non-403/non-401.
_ADMIN_ROUTES: list[tuple[str, str, dict | None, frozenset[str]]] = [
    ("POST", "/admin/clients", {"name": "x", "slug": "x"}, frozenset({"super_admin"})),
    ("GET", "/admin/clients", None, frozenset({"super_admin"})),
    ("GET", "/admin/clients/1", None, frozenset({"super_admin"})),
    ("PUT", "/admin/clients/1", {}, frozenset({"super_admin"})),
    ("DELETE", "/admin/clients/1", None, frozenset({"super_admin"})),
    ("GET", "/admin/clients/1/stats", None, frozenset({"super_admin"})),
    ("POST", "/admin/users", {"email": "x@x.com", "full_name": "x"}, frozenset({"super_admin"})),
    ("GET", "/admin/users", None, frozenset({"super_admin", "tenant_admin"})),
    ("GET", "/admin/users/x", None, frozenset({"super_admin", "tenant_admin"})),
    ("PUT", "/admin/users/x", {}, frozenset({"super_admin"})),
    ("DELETE", "/admin/users/x", None, frozenset({"super_admin"})),
    ("GET", "/admin/calls", None, frozenset({"super_admin", "tenant_admin"})),
    ("GET", "/admin/calls/1", None, frozenset({"super_admin", "tenant_admin"})),
    ("POST", "/admin/tenants", {"name": "x", "slug": "x"}, frozenset({"super_admin"})),
    ("GET", "/admin/tenants", None, frozenset({"super_admin"})),
    ("GET", "/admin/tenants/1", None, frozenset({"super_admin"})),
    ("PUT", "/admin/tenants/1", {}, frozenset({"super_admin"})),
    ("DELETE", "/admin/tenants/1", None, frozenset({"super_admin"})),
    ("GET", "/admin/tenants/1/stats", None, frozenset({"super_admin"})),
]

# Routes that require *any* authenticated role (no RBAC gate beyond login) —
# services/api/src/main.py's make_call/me/logout, not services/api/src/
# routers/admin.py.
_OPEN_TO_ANY_AUTHENTICATED_ROLE: list[tuple[str, str, dict | None]] = [
    (
        "POST",
        "/call",
        {
            "customer_name": "x",
            "phone_number": "+919876543210",
            "hotel_name": "x",
            "check_in_date": "2026-09-01",
            "check_out_date": "2026-09-02",
        },
    ),
    ("GET", "/auth/me", None),
    ("POST", "/auth/logout", None),
]

_ALL_ROLES = ("agent", "tenant_admin", "super_admin")

# /client/* routes — accessible to tenant_admin and agent only.
# super_admin gets 403 (explicitly blocked by _require_client).
# Routes that also require tenant_admin (via _require_client_admin) are marked
# with a narrower allowed set.
_CLIENT_ROUTES: list[tuple[str, str, dict | None, frozenset[str]]] = [
    # Customer CRUD — accessible to both tenant_admin and agent
    (
        "GET",
        "/client/customers",
        None,
        frozenset({"tenant_admin", "agent"}),
    ),
    (
        "POST",
        "/client/customers",
        {"phone": "+971509999999"},
        frozenset({"tenant_admin", "agent"}),
    ),
    (
        "GET",
        "/client/customers/nonexistent-uuid",
        None,
        frozenset({"tenant_admin", "agent"}),
    ),
    (
        "PUT",
        "/client/customers/nonexistent-uuid",
        {"name": "X"},
        frozenset({"tenant_admin", "agent"}),
    ),
    # Call log — accessible to both
    ("GET", "/client/calls", None, frozenset({"tenant_admin", "agent"})),
    # Analytics — tenant_admin only
    ("GET", "/client/analytics", None, frozenset({"tenant_admin"})),
    # Users — tenant_admin only
    ("GET", "/client/users", None, frozenset({"tenant_admin"})),
]


def _token_for(role: str) -> str:
    payload = {
        "sub": f"{role}@matrix.test",
        "role": role,
        "exp": datetime.now(UTC) + timedelta(minutes=30),
        "type": "access",
    }
    if role in ("tenant_admin", "agent"):
        payload["client_id"] = 999
    return jwt.encode(payload, _JWT_SECRET, _JWT_ALG)


def _headers(role: str) -> dict:
    return {"Authorization": f"Bearer {_token_for(role)}"}


@pytest.mark.parametrize("method,path,body,allowed_roles", _ADMIN_ROUTES)
async def test_admin_route_rejects_unauthenticated(
    api_client: AsyncClient, method: str, path: str, body, allowed_roles
):
    r = await api_client.request(method, path, json=body if body is not None else {})
    assert (
        r.status_code == 401
    ), f"{method} {path} (no token) returned {r.status_code}, expected 401"


@pytest.mark.parametrize("method,path,body,allowed_roles", _ADMIN_ROUTES)
@pytest.mark.parametrize("role", _ALL_ROLES)
async def test_admin_route_role_gate(
    api_client: AsyncClient, method: str, path: str, body, allowed_roles, role: str
):
    r = await api_client.request(
        method, path, json=body if body is not None else {}, headers=_headers(role)
    )
    if role in allowed_roles:
        assert (
            r.status_code != 403
        ), f"{method} {path}: role={role} should be allowed past RBAC but got 403"
        assert r.status_code != 401
    else:
        assert (
            r.status_code == 403
        ), f"{method} {path}: role={role} should be rejected but got {r.status_code}"


@pytest.mark.parametrize("method,path,body", _OPEN_TO_ANY_AUTHENTICATED_ROLE)
async def test_open_route_rejects_unauthenticated(
    api_client: AsyncClient, method: str, path: str, body
):
    r = await api_client.request(method, path, json=body if body is not None else {})
    assert (
        r.status_code == 401
    ), f"{method} {path} (no token) returned {r.status_code}, expected 401"


@pytest.mark.parametrize("method,path,body", _OPEN_TO_ANY_AUTHENTICATED_ROLE)
@pytest.mark.parametrize("role", _ALL_ROLES)
async def test_open_route_allows_every_authenticated_role(
    api_client: AsyncClient, method: str, path: str, body, role: str
):
    r = await api_client.request(
        method, path, json=body if body is not None else {}, headers=_headers(role)
    )
    assert r.status_code not in (
        401,
        403,
    ), f"{method} {path}: role={role} should never be RBAC-rejected here, got {r.status_code}"


@pytest.mark.parametrize("method,path,body,allowed_roles", _CLIENT_ROUTES)
async def test_client_route_rejects_unauthenticated(
    api_client: AsyncClient, method: str, path: str, body, allowed_roles
):
    r = await api_client.request(method, path, json=body if body is not None else {})
    assert r.status_code == 401, (
        f"{method} {path} (no token) returned {r.status_code}, expected 401"
    )


@pytest.mark.parametrize("method,path,body,allowed_roles", _CLIENT_ROUTES)
@pytest.mark.parametrize("role", _ALL_ROLES)
async def test_client_route_role_gate(
    api_client: AsyncClient, method: str, path: str, body, allowed_roles, role: str
):
    r = await api_client.request(
        method, path, json=body if body is not None else {}, headers=_headers(role)
    )
    if role in allowed_roles:
        assert r.status_code != 403, (
            f"{method} {path}: role={role} should be allowed past RBAC but got 403"
        )
        assert r.status_code != 401
    else:
        assert r.status_code == 403, (
            f"{method} {path}: role={role} should be rejected but got {r.status_code}"
        )


async def test_tampered_jwt_signature_rejected_on_every_admin_route(api_client: AsyncClient):
    """Testing Guide §6: an expired or tampered JWT is rejected on every
    protected endpoint, not just some."""
    real = _token_for("super_admin")
    tampered = real[:-4] + ("AAAA" if not real.endswith("AAAA") else "BBBB")
    headers = {"Authorization": f"Bearer {tampered}"}
    for method, path, body, _allowed in _ADMIN_ROUTES:
        r = await api_client.request(
            method, path, json=body if body is not None else {}, headers=headers
        )
        assert r.status_code == 401, f"{method} {path} accepted a tampered JWT signature"


async def test_expired_jwt_rejected_on_every_admin_route(api_client: AsyncClient):
    expired = jwt.encode(
        {
            "sub": "x@x.com",
            "role": "super_admin",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "type": "access",
        },
        _JWT_SECRET,
        _JWT_ALG,
    )
    headers = {"Authorization": f"Bearer {expired}"}
    for method, path, body, _allowed in _ADMIN_ROUTES:
        r = await api_client.request(
            method, path, json=body if body is not None else {}, headers=headers
        )
        assert r.status_code == 401, f"{method} {path} accepted an expired JWT"
