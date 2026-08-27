"""NK-07 — per-request tenant context for PostgreSQL Row-Level Security.

Database Design §6 is explicit that tenant isolation cannot depend on every
query remembering a WHERE clause — RLS is the second, independent layer that
holds even when application code forgets one. This module is the other half
of that: it sets the `app.current_tenant` session setting the RLS policies
(alembic/versions/df467b3bdd3f_*) compare against.

Uses `set_config(..., false)` — SESSION-scoped, not `SET LOCAL`/`true`
(transaction-scoped) as the Database Design doc's illustrative example shows.
That example assumes one transaction per request; this codebase's routers
don't (routers/admin.py routinely does add → commit → refresh in a single
handler), and SET LOCAL resets the instant that first commit happens — every
query issued after it, still within the same request/session, would see no
tenant context at all and fail closed to zero rows. Session scope survives
across commits within one session, which is what a request actually needs.

The trade the doc warns about doesn't go away, it moves: a session-scoped
setting persists on the underlying connection past your session's usage of
it, so it MUST be cleared before that connection returns to the pool, or the
next unrelated request that happens to reuse it inherits this one's tenant.
src/database.py's get_db() does that reset in its `finally` — this module
must never be used with a get_db() that doesn't.

A no-op against non-PostgreSQL engines (the test suite's in-memory SQLite has
no equivalent GUC/RLS mechanism) — RLS behaviour itself is verified against a
real Postgres in tests/test_tenant_isolation.py, not the SQLite unit suite.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db

# Must match _ALL_TENANTS_SENTINEL in
# alembic/versions/df467b3bdd3f_nk07_tenant_row_level_security.py exactly —
# it's what every RLS policy's bypass clause compares against. Deliberately
# not '' or NULL: those are what an *unset* GUC already looks like, and the
# policies are designed to fail closed (zero rows) in that case, not open.
_ALL_TENANTS_SENTINEL = "__all_tenants__"


async def _set_tenant_context(db: AsyncSession, tenant_value: str) -> AsyncSession:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return db
    await db.execute(
        text("SELECT set_config('app.current_tenant', :tenant, false)"),
        {"tenant": tenant_value},
    )
    return db


async def get_tenant_scoped_db(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncSession:
    """Drop-in replacement for `Depends(get_db)` on any authenticated,
    tenant-facing route. Sets app.current_tenant for this transaction to the
    caller's tenant — or to the cross-tenant sentinel for super_admin.

    A route that uses plain `get_db` instead of this dependency never sets
    app.current_tenant at all, and the RLS policies fail closed for that case
    (zero rows, not every row) — so forgetting to wire this in produces a
    visibly broken endpoint, not a silent cross-tenant leak.
    """
    role = user.get("role", "agent")
    tenant_value = (
        _ALL_TENANTS_SENTINEL if role == "super_admin" else str(user.get("client_id") or "")
    )
    return await _set_tenant_context(db, tenant_value)


async def get_internal_service_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """For routers/internal.py — the voice gateway's service-to-service API,
    with no JWT/user identity to read a tenant from (it operates on whatever
    tenant a call's own phone-number routing resolved to, across every
    tenant, by design). Always uses the cross-tenant sentinel: this is a
    trusted, network-internal caller (analogous to super_admin's platform-
    level access), not a route that forgot to scope itself. If this endpoint
    is ever exposed to untrusted callers, it needs its own authentication
    layer before RLS scoping is meaningful here at all.
    """
    return await _set_tenant_context(db, _ALL_TENANTS_SENTINEL)


async def get_login_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """For POST /auth/login only.

    Login has to find an admin_users row by email before any tenant is
    known — there is no JWT yet to read a tenant from, and the row's own
    tenant_id is exactly what this lookup is trying to discover. Without this,
    the tenant_isolation policy on admin_users (correctly) shows zero rows to
    a plain get_db() connection, so no DB-backed (non-bootstrap) user could
    ever log in against a real RLS-enforced database — confirmed live: the
    lookup query still filters on the caller-supplied email, so this grants
    visibility to search by email, not to read arbitrary cross-tenant data.
    Same cross-tenant-sentinel reasoning as get_internal_service_db above:
    this is the trusted entry point that *establishes* tenant identity, not a
    route that forgot to scope itself. Every route after login uses the
    resulting JWT's tenant_id via get_tenant_scoped_db instead.
    """
    return await _set_tenant_context(db, _ALL_TENANTS_SENTINEL)
