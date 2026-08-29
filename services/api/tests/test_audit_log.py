"""
NK-16 — Audit logging.

Database Design §5 (audit_logs): one row per sensitive action — role
changes, admin actions on a client account. The AuditLog model
(services/api/src/models.py) and table existed before this ticket but
nothing wrote to it (see PROGRESS.md's 2026-08-26 session log). This file
proves the write side (services/api/src/routers/admin.py's
_write_audit_log, wired into every client/tenant/user mutation) and the
read side (GET /admin/audit-logs).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuditLog

pytestmark = pytest.mark.asyncio


async def _audit_rows(db: AsyncSession) -> list[AuditLog]:
    return list((await db.execute(select(AuditLog))).scalars().all())


async def test_create_client_writes_audit_row(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict
):
    r = await api_client.post(
        "/admin/clients",
        json={"name": "Acme", "slug": "acme-audit"},
        headers=super_admin_headers,
    )
    assert r.status_code == 201
    client_id = r.json()["id"]

    rows = await _audit_rows(db_session)
    assert len(rows) == 1
    assert rows[0].action == "client.create"
    assert rows[0].tenant_id == str(client_id)
    assert rows[0].before_value is None
    assert rows[0].after_value["slug"] == "acme-audit"


async def test_update_client_writes_before_and_after(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict
):
    created = await api_client.post(
        "/admin/clients", json={"name": "Old Name", "slug": "rename-me"}, headers=super_admin_headers
    )
    client_id = created.json()["id"]

    r = await api_client.put(
        f"/admin/clients/{client_id}", json={"name": "New Name"}, headers=super_admin_headers
    )
    assert r.status_code == 200

    rows = await _audit_rows(db_session)
    update_rows = [row for row in rows if row.action == "client.update"]
    assert len(update_rows) == 1
    assert update_rows[0].before_value["name"] == "Old Name"
    assert update_rows[0].after_value["name"] == "New Name"


async def test_delete_client_writes_audit_row_with_status_transition(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict
):
    created = await api_client.post(
        "/admin/clients", json={"name": "Doomed", "slug": "doomed"}, headers=super_admin_headers
    )
    client_id = created.json()["id"]

    r = await api_client.delete(f"/admin/clients/{client_id}", headers=super_admin_headers)
    assert r.status_code == 204

    rows = await _audit_rows(db_session)
    delete_rows = [row for row in rows if row.action == "client.delete"]
    assert len(delete_rows) == 1
    assert delete_rows[0].before_value["status"] == "active"
    assert delete_rows[0].after_value["status"] == "inactive"


async def test_user_role_change_is_captured_in_before_after(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict
):
    tenant = await api_client.post(
        "/admin/clients", json={"name": "T", "slug": "role-change-tenant"}, headers=super_admin_headers
    )
    tenant_id = tenant.json()["id"]
    created = await api_client.post(
        "/admin/users",
        json={"email": "promote-me@x.com", "full_name": "X", "role": "agent", "tenant_id": tenant_id},
        headers=super_admin_headers,
    )
    user_id = created.json()["user_id"]

    r = await api_client.put(
        f"/admin/users/{user_id}", json={"role": "tenant_admin"}, headers=super_admin_headers
    )
    assert r.status_code == 200

    rows = await _audit_rows(db_session)
    update_rows = [row for row in rows if row.action == "user.update"]
    assert len(update_rows) == 1
    assert update_rows[0].before_value["role"] == "agent"
    assert update_rows[0].after_value["role"] == "tenant_admin"


async def test_user_audit_snapshot_never_contains_password_hash(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict
):
    r = await api_client.post(
        "/admin/users",
        json={"email": "secret@x.com", "full_name": "X", "role": "agent", "password": "supersecret1"},
        headers=super_admin_headers,
    )
    assert r.status_code == 201

    rows = await _audit_rows(db_session)
    assert len(rows) == 1
    assert "password" not in rows[0].after_value
    assert "password_hash" not in rows[0].after_value


async def test_super_admin_can_list_all_audit_logs(
    api_client: AsyncClient, super_admin_headers: dict
):
    await api_client.post(
        "/admin/clients", json={"name": "A", "slug": "audit-list-a"}, headers=super_admin_headers
    )
    await api_client.post(
        "/admin/clients", json={"name": "B", "slug": "audit-list-b"}, headers=super_admin_headers
    )

    r = await api_client.get("/admin/audit-logs", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all(row["action"] == "client.create" for row in body["data"])


async def test_audit_logs_filterable_by_action(api_client: AsyncClient, super_admin_headers: dict):
    created = await api_client.post(
        "/admin/clients", json={"name": "C", "slug": "audit-filter"}, headers=super_admin_headers
    )
    client_id = created.json()["id"]
    await api_client.put(
        f"/admin/clients/{client_id}", json={"name": "C2"}, headers=super_admin_headers
    )

    r = await api_client.get("/admin/audit-logs?action=client.update", headers=super_admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["data"][0]["action"] == "client.update"


async def test_tenant_admin_only_sees_own_tenant_audit_logs(
    api_client: AsyncClient, db_session: AsyncSession, super_admin_headers: dict, make_tenant_admin_headers
):
    own = await api_client.post(
        "/admin/clients", json={"name": "Own", "slug": "audit-own"}, headers=super_admin_headers
    )
    other = await api_client.post(
        "/admin/clients", json={"name": "Other", "slug": "audit-other"}, headers=super_admin_headers
    )
    own_id, other_id = own.json()["id"], other.json()["id"]

    # A mutation on each tenant, so each has an audit row.
    await api_client.put(f"/admin/clients/{own_id}", json={"name": "Own2"}, headers=super_admin_headers)
    await api_client.put(f"/admin/clients/{other_id}", json={"name": "Other2"}, headers=super_admin_headers)

    headers = make_tenant_admin_headers(client_id=own_id)
    r = await api_client.get("/admin/audit-logs", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert all(row["tenant_id"] == str(own_id) for row in body["data"])
    assert not any(row["tenant_id"] == str(other_id) for row in body["data"])


async def test_tenant_admin_cannot_escalate_audit_logs_via_query_param(
    api_client: AsyncClient, super_admin_headers: dict, make_tenant_admin_headers
):
    own = await api_client.post(
        "/admin/clients", json={"name": "Own", "slug": "audit-esc-own"}, headers=super_admin_headers
    )
    other = await api_client.post(
        "/admin/clients", json={"name": "Other", "slug": "audit-esc-other"}, headers=super_admin_headers
    )
    own_id, other_id = own.json()["id"], other.json()["id"]

    headers = make_tenant_admin_headers(client_id=own_id)
    r = await api_client.get(f"/admin/audit-logs?tenant_id={other_id}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    # The query param asking for tenant B must be ignored, not honored — the
    # response is still scoped to tenant A (which has exactly one audit row
    # of its own, from being created), never tenant B's.
    assert all(row["tenant_id"] == str(own_id) for row in body["data"])
    assert not any(row["tenant_id"] == str(other_id) for row in body["data"])


async def test_agent_role_rejected_on_audit_logs(api_client: AsyncClient, agent_headers: dict):
    r = await api_client.get("/admin/audit-logs", headers=agent_headers)
    assert r.status_code == 403
