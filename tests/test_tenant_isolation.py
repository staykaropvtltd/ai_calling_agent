"""NK-07 / NK-08 — PostgreSQL Row-Level Security isolation tests.

Unlike the rest of the suite, this exercises real RLS policies (alembic/
versions/df467b3bdd3f_nk07_tenant_row_level_security.py) directly over a raw
asyncpg connection — RLS is a Postgres-only mechanism with no SQLite
equivalent, so it cannot be verified through services/api/tests/conftest.py's
in-memory SQLite fixtures the way the rest of the API test suite is.

Requires a real Postgres reachable at TEST_POSTGRES_DSN (defaults to this
project's docker-compose mapping, 127.0.0.1:5433) with migrations already
applied through df467b3bdd3f, and skips cleanly — not a failure — when either
isn't true, since CI's `test` job (unlike this local/dev environment) has no
Postgres service and never will run this file. Run manually with a live stack:

    docker compose up -d postgres
    cd services/api && MIGRATION_DATABASE_URL=... APP_DB_PASSWORD=... \
        python -m alembic upgrade head
    pytest tests/test_tenant_isolation.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

asyncpg = pytest.importorskip("asyncpg")

pytestmark = pytest.mark.asyncio

_SUPERUSER_DSN = os.environ.get(
    "TEST_POSTGRES_DSN",
    "postgresql://staykaro_user:change_me_in_production@127.0.0.1:5433/staykaro",
)
_APP_PASSWORD = os.environ.get("TEST_APP_DB_PASSWORD", "app-dev-password")
_APP_DSN = os.environ.get(
    "TEST_APP_POSTGRES_DSN",
    f"postgresql://staykaro_app:{_APP_PASSWORD}@127.0.0.1:5433/staykaro",
)

_ALL_TENANTS_SENTINEL = "__all_tenants__"


async def _connect_or_skip(dsn: str) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(dsn, timeout=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Real Postgres not reachable at {dsn!r} — skipping RLS tests: {exc}")


async def _require_rls_migrated(conn) -> None:
    row = await conn.fetchrow(
        "SELECT 1 FROM pg_policies WHERE tablename = 'call_requests' "
        "AND policyname = 'tenant_isolation'"
    )
    if row is None:
        pytest.skip(
            "df467b3bdd3f (NK-07 RLS) not applied to this database — "
            "run `alembic upgrade head` with MIGRATION_DATABASE_URL set first."
        )


@pytest.fixture
async def two_tenants():
    """Seed two Client rows and one call_requests row each, as the superuser
    (migration role) — RLS never restricts inserts made outside a tenant
    context in the first place, so setup doesn't need app-role privileges.
    Cleans up unconditionally, even if a test fails partway through.
    """
    admin = await _connect_or_skip(_SUPERUSER_DSN)
    await _require_rls_migrated(admin)

    tenant_a = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Test Tenant A",
        f"rls-test-a-{os.getpid()}",
    )
    tenant_b = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Test Tenant B",
        f"rls-test-b-{os.getpid()}",
    )
    call_a = await admin.fetchval(
        "INSERT INTO call_requests (customer_name, phone_number, hotel_name, "
        "check_in_date, check_out_date, client_id) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
        "Alice",
        "+911111111111",
        "Hotel A",
        "2026-01-01",
        "2026-01-02",
        tenant_a,
    )
    call_b = await admin.fetchval(
        "INSERT INTO call_requests (customer_name, phone_number, hotel_name, "
        "check_in_date, check_out_date, client_id) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id",
        "Bob",
        "+912222222222",
        "Hotel B",
        "2026-01-01",
        "2026-01-02",
        tenant_b,
    )

    try:
        yield {"tenant_a": tenant_a, "tenant_b": tenant_b, "call_a": call_a, "call_b": call_b}
    finally:
        await admin.execute(
            "DELETE FROM call_requests WHERE id = ANY($1::int[])", [call_a, call_b]
        )
        await admin.execute(
            "DELETE FROM clients WHERE id = ANY($1::int[])", [tenant_a, tenant_b]
        )
        await admin.close()


@pytest.fixture
async def app_conn():
    conn = await _connect_or_skip(_APP_DSN)
    try:
        yield conn
    finally:
        await conn.close()


async def _set_tenant(conn, value: str) -> None:
    # false = session-scoped, matching src/tenant.py exactly. Not `true`
    # (SET LOCAL): routers/admin.py routinely commits mid-handler (add then
    # commit then refresh), and a transaction-scoped setting resets the
    # instant that first commit happens — everything after it in the same
    # request would see no tenant context and fail closed. Session scope
    # survives across commits; src/database.py's get_db() is responsible for
    # clearing it before the connection returns to the pool instead — see
    # test_tenant_context_survives_commit_but_is_cleared_on_reset below.
    await conn.execute("SELECT set_config('app.current_tenant', $1, false)", value)


async def test_app_role_is_not_superuser_and_does_not_bypass_rls(app_conn):
    """The whole migration exists because staykaro_user (superuser) silently
    bypasses RLS — this pins down that staykaro_app does not have the same
    problem, so a future role rename/misconfiguration fails loudly here."""
    row = await app_conn.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    assert row["rolsuper"] is False
    assert row["rolbypassrls"] is False


async def test_tenant_sees_only_its_own_call(app_conn, two_tenants):
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
        rows = await app_conn.fetch(
            "SELECT id, client_id FROM call_requests WHERE id = ANY($1::int[])",
            [two_tenants["call_a"], two_tenants["call_b"]],
        )
        assert [r["id"] for r in rows] == [two_tenants["call_a"]]


async def test_other_tenant_sees_only_its_own_call(app_conn, two_tenants):
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenants["tenant_b"]))
        rows = await app_conn.fetch(
            "SELECT id, client_id FROM call_requests WHERE id = ANY($1::int[])",
            [two_tenants["call_a"], two_tenants["call_b"]],
        )
        assert [r["id"] for r in rows] == [two_tenants["call_b"]]


async def test_no_tenant_context_set_fails_closed_not_open(app_conn, two_tenants):
    """The critical regression this guards against: a route that forgets to
    wire get_tenant_scoped_db must see NOTHING, not everything."""
    rows = await app_conn.fetch(
        "SELECT id FROM call_requests WHERE id = ANY($1::int[])",
        [two_tenants["call_a"], two_tenants["call_b"]],
    )
    assert rows == []


async def test_all_tenants_sentinel_sees_both(app_conn, two_tenants):
    async with app_conn.transaction():
        await _set_tenant(app_conn, _ALL_TENANTS_SENTINEL)
        rows = await app_conn.fetch(
            "SELECT id FROM call_requests WHERE id = ANY($1::int[])",
            [two_tenants["call_a"], two_tenants["call_b"]],
        )
        assert {r["id"] for r in rows} == {two_tenants["call_a"], two_tenants["call_b"]}


async def test_cross_tenant_insert_is_rejected(app_conn, two_tenants):
    """WITH CHECK, not just USING: a tenant cannot write a row claiming to
    belong to a different tenant, even though it's an INSERT (no prior row
    to filter) rather than a read."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
            await app_conn.execute(
                "INSERT INTO call_requests (customer_name, phone_number, hotel_name, "
                "check_in_date, check_out_date, client_id) VALUES ($1,$2,$3,$4,$5,$6)",
                "Eve",
                "+913333333333",
                "Hotel E",
                "2026-01-01",
                "2026-01-02",
                two_tenants["tenant_b"],
            )


async def test_cross_tenant_update_is_rejected(app_conn, two_tenants):
    """A tenant cannot re-point its own row at another tenant via UPDATE."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
            await app_conn.execute(
                "UPDATE call_requests SET client_id = $1 WHERE id = $2",
                two_tenants["tenant_b"],
                two_tenants["call_a"],
            )


async def test_cross_tenant_delete_is_rejected(app_conn, two_tenants):
    """A tenant's DELETE cannot target another tenant's row. Unlike INSERT/
    UPDATE (WITH CHECK raises InsufficientPrivilegeError), DELETE is governed
    by USING alone: the row is simply not visible to the DELETE, so it
    reports zero rows affected rather than raising — assert both that outcome
    and that the row genuinely survives."""
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
        result = await app_conn.execute(
            "DELETE FROM call_requests WHERE id = $1", two_tenants["call_b"]
        )
        assert result == "DELETE 0"

    # Confirm as tenant B that its own row is untouched.
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenants["tenant_b"]))
        row = await app_conn.fetchrow(
            "SELECT id FROM call_requests WHERE id = $1", two_tenants["call_b"]
        )
        assert row is not None


async def test_tenant_context_survives_a_mid_request_commit(app_conn, two_tenants):
    """Regression test for the actual bug hit building this: routers/admin.py
    does add() -> commit() -> refresh() in one handler. A transaction-scoped
    (SET LOCAL) tenant context would reset the instant that commit happens,
    so refresh() — issued after it, same session, same request — would see
    no tenant context and silently return nothing. Session-scoped set_config
    must survive exactly this."""
    await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
    async with app_conn.transaction():
        rows = await app_conn.fetch(
            "SELECT id FROM call_requests WHERE id = $1", two_tenants["call_a"]
        )
        assert len(rows) == 1
    # Transaction committed — a *different*, later statement on the same
    # connection/session must still see tenant A's context, not lose it.
    rows_after_commit = await app_conn.fetch(
        "SELECT id FROM call_requests WHERE id = $1", two_tenants["call_a"]
    )
    assert len(rows_after_commit) == 1


async def test_tenant_context_is_cleared_by_explicit_reset(app_conn, two_tenants):
    """The other half of the trade: because the context now survives commits
    (previous test), it also survives past one logical "request" on a pooled
    connection unless something explicitly clears it — src/database.py's
    get_db() does that with RESET in its `finally`. Simulates get_db()'s
    cleanup directly and confirms it actually closes the gap."""
    await _set_tenant(app_conn, str(two_tenants["tenant_a"]))
    rows = await app_conn.fetch(
        "SELECT id FROM call_requests WHERE id = $1", two_tenants["call_a"]
    )
    assert len(rows) == 1

    await app_conn.execute("RESET app.current_tenant")

    # Simulates the next, unrelated request reusing this pooled connection
    # with no tenant context of its own yet — must be fail-closed, not still
    # carrying tenant A's access forward.
    rows_after_reset = await app_conn.fetch(
        "SELECT id FROM call_requests WHERE id = ANY($1::int[])",
        [two_tenants["call_a"], two_tenants["call_b"]],
    )
    assert rows_after_reset == []


# ── Phase 3 — `calls` table (SH-03 call/session records, distinct from the
# legacy `call_requests` table exercised above) ────────────────────────────
#
# Same RLS policy shape (tenant_isolation on df467b3bdd3f), but calls.tenant_id
# is already text (no ::text cast needed) and calls.call_id is the voice
# gateway's own UUID string, not an autoincrement int — a real, separate proof
# that RLS holds for the table Phase 3's internal API and voice gateway
# actually write to, not just the legacy /call endpoint's table.


@pytest.fixture
async def two_tenant_calls():
    admin = await _connect_or_skip(_SUPERUSER_DSN)
    await _require_rls_migrated(admin)

    tenant_a = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Calls Tenant A",
        f"rls-calls-a-{os.getpid()}",
    )
    tenant_b = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Calls Tenant B",
        f"rls-calls-b-{os.getpid()}",
    )
    call_a = f"rls-call-a-{os.getpid()}"
    call_b = f"rls-call-b-{os.getpid()}"
    now = datetime.now(UTC)
    await admin.execute(
        "INSERT INTO calls (call_id, tenant_id, agent_id, status, started_at) "
        "VALUES ($1, $2, $3, 'active', $4)",
        call_a,
        str(tenant_a),
        "agent-a",
        now,
    )
    await admin.execute(
        "INSERT INTO calls (call_id, tenant_id, agent_id, status, started_at) "
        "VALUES ($1, $2, $3, 'active', $4)",
        call_b,
        str(tenant_b),
        "agent-b",
        now,
    )

    try:
        yield {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "call_a": call_a,
            "call_b": call_b,
        }
    finally:
        await admin.execute(
            "DELETE FROM calls WHERE call_id = ANY($1::text[])", [call_a, call_b]
        )
        await admin.execute(
            "DELETE FROM clients WHERE id = ANY($1::int[])", [tenant_a, tenant_b]
        )
        await admin.close()


async def test_calls_table_tenant_sees_only_its_own_call(app_conn, two_tenant_calls):
    await _set_tenant(app_conn, str(two_tenant_calls["tenant_a"]))
    rows = await app_conn.fetch("SELECT call_id FROM calls")
    assert {r["call_id"] for r in rows} == {two_tenant_calls["call_a"]}


async def test_calls_table_cross_tenant_read_returns_nothing(app_conn, two_tenant_calls):
    await _set_tenant(app_conn, str(two_tenant_calls["tenant_a"]))
    row = await app_conn.fetchrow(
        "SELECT call_id FROM calls WHERE call_id = $1", two_tenant_calls["call_b"]
    )
    assert row is None


async def test_calls_table_cross_tenant_finalize_affects_nothing(app_conn, two_tenant_calls):
    """The exact operation routers/internal.py::finalize_call performs
    (UPDATE ... SET ended_at/status), attempted by the wrong tenant."""
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenant_calls["tenant_a"]))
        result = await app_conn.execute(
            "UPDATE calls SET status = 'completed', ended_at = now() WHERE call_id = $1",
            two_tenant_calls["call_b"],
        )
        assert result == "UPDATE 0"

    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenant_calls["tenant_b"]))
        row = await app_conn.fetchrow(
            "SELECT status, ended_at FROM calls WHERE call_id = $1", two_tenant_calls["call_b"]
        )
        assert row["status"] == "active"
        assert row["ended_at"] is None


async def test_calls_table_cross_tenant_insert_is_rejected(app_conn, two_tenant_calls):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _set_tenant(app_conn, str(two_tenant_calls["tenant_a"]))
            await app_conn.execute(
                "INSERT INTO calls (call_id, tenant_id, agent_id, status, started_at) "
                "VALUES ($1, $2, $3, 'active', now())",
                f"rls-call-forged-{os.getpid()}",
                str(two_tenant_calls["tenant_b"]),
                "agent-x",
            )


async def test_calls_table_no_tenant_context_fails_closed(app_conn, two_tenant_calls):
    rows = await app_conn.fetch(
        "SELECT call_id FROM calls WHERE call_id = ANY($1::text[])",
        [two_tenant_calls["call_a"], two_tenant_calls["call_b"]],
    )
    assert rows == []


async def test_calls_table_all_tenants_sentinel_sees_both(app_conn, two_tenant_calls):
    """The internal API's get_internal_service_db uses exactly this sentinel
    — matches how the voice gateway is trusted to read/write across tenants."""
    await _set_tenant(app_conn, _ALL_TENANTS_SENTINEL)
    rows = await app_conn.fetch(
        "SELECT call_id FROM calls WHERE call_id = ANY($1::text[])",
        [two_tenant_calls["call_a"], two_tenant_calls["call_b"]],
    )
    assert {r["call_id"] for r in rows} == {
        two_tenant_calls["call_a"],
        two_tenant_calls["call_b"],
    }


# ── Phase 6 — `call_jobs` table (durable job/event record, distinct from the
# audit-only `call_events` table and never reused as one — see
# services/api/src/models.py::CallJob's docstring) ─────────────────────────
#
# Same RLS policy shape as `calls`, added in a NEW migration
# (7b1c9e2a4f3d_phase6_call_jobs.py) rather than editing df467b3bdd3f.
# tenant_id is nullable here (unlike calls.tenant_id) — a job recorded before
# routing resolves a tenant has none yet — so these tests also cover that a
# NULL-tenant row is invisible under a real tenant context and only visible
# under the __all_tenants__ bypass, never under "no context at all".


@pytest.fixture
async def two_tenant_jobs():
    admin = await _connect_or_skip(_SUPERUSER_DSN)
    row = await admin.fetchrow(
        "SELECT 1 FROM pg_policies WHERE tablename = 'call_jobs' "
        "AND policyname = 'tenant_isolation'"
    )
    if row is None:
        await admin.close()
        pytest.skip(
            "7b1c9e2a4f3d (Phase 6 call_jobs RLS) not applied to this database — "
            "run `alembic upgrade head` with MIGRATION_DATABASE_URL set first."
        )

    tenant_a = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Jobs Tenant A",
        f"rls-jobs-a-{os.getpid()}",
    )
    tenant_b = await admin.fetchval(
        "INSERT INTO clients (name, slug) VALUES ($1, $2) RETURNING id",
        "RLS Jobs Tenant B",
        f"rls-jobs-b-{os.getpid()}",
    )
    job_a = await admin.fetchval(
        "INSERT INTO call_jobs (job_id, tenant_id, event_type, provider_call_id) "
        "VALUES (gen_random_uuid()::text, $1, 'connected', $2) RETURNING job_id",
        str(tenant_a),
        f"rls-job-provider-a-{os.getpid()}",
    )
    job_b = await admin.fetchval(
        "INSERT INTO call_jobs (job_id, tenant_id, event_type, provider_call_id) "
        "VALUES (gen_random_uuid()::text, $1, 'connected', $2) RETURNING job_id",
        str(tenant_b),
        f"rls-job-provider-b-{os.getpid()}",
    )
    job_no_tenant = await admin.fetchval(
        "INSERT INTO call_jobs (job_id, tenant_id, event_type, provider_call_id) "
        "VALUES (gen_random_uuid()::text, NULL, 'connected', $1) RETURNING job_id",
        f"rls-job-provider-null-{os.getpid()}",
    )

    try:
        yield {
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "job_a": job_a,
            "job_b": job_b,
            "job_no_tenant": job_no_tenant,
        }
    finally:
        await admin.execute(
            "DELETE FROM call_jobs WHERE job_id = ANY($1::text[])",
            [job_a, job_b, job_no_tenant],
        )
        await admin.execute(
            "DELETE FROM clients WHERE id = ANY($1::int[])", [tenant_a, tenant_b]
        )
        await admin.close()


async def test_call_jobs_tenant_sees_only_its_own_job(app_conn, two_tenant_jobs):
    await _set_tenant(app_conn, str(two_tenant_jobs["tenant_a"]))
    rows = await app_conn.fetch("SELECT job_id FROM call_jobs")
    assert {r["job_id"] for r in rows} == {two_tenant_jobs["job_a"]}


async def test_call_jobs_cross_tenant_read_returns_nothing(app_conn, two_tenant_jobs):
    await _set_tenant(app_conn, str(two_tenant_jobs["tenant_a"]))
    row = await app_conn.fetchrow(
        "SELECT job_id FROM call_jobs WHERE job_id = $1", two_tenant_jobs["job_b"]
    )
    assert row is None


async def test_call_jobs_cross_tenant_claim_affects_nothing(app_conn, two_tenant_jobs):
    """The exact operation routers/jobs.py::claim_event performs, attempted
    against a job belonging to a different tenant."""
    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenant_jobs["tenant_a"]))
        result = await app_conn.execute(
            "UPDATE call_jobs SET status = 'processing', attempts = attempts + 1 "
            "WHERE job_id = $1 AND status = 'queued'",
            two_tenant_jobs["job_b"],
        )
        assert result == "UPDATE 0"

    async with app_conn.transaction():
        await _set_tenant(app_conn, str(two_tenant_jobs["tenant_b"]))
        row = await app_conn.fetchrow(
            "SELECT status, attempts FROM call_jobs WHERE job_id = $1", two_tenant_jobs["job_b"]
        )
        assert row["status"] == "queued"
        assert row["attempts"] == 0


async def test_call_jobs_cross_tenant_insert_is_rejected(app_conn, two_tenant_jobs):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_conn.transaction():
            await _set_tenant(app_conn, str(two_tenant_jobs["tenant_a"]))
            await app_conn.execute(
                "INSERT INTO call_jobs (job_id, tenant_id, event_type) "
                "VALUES (gen_random_uuid()::text, $1, 'forged')",
                str(two_tenant_jobs["tenant_b"]),
            )


async def test_call_jobs_no_tenant_context_fails_closed(app_conn, two_tenant_jobs):
    rows = await app_conn.fetch(
        "SELECT job_id FROM call_jobs WHERE job_id = ANY($1::text[])",
        [two_tenant_jobs["job_a"], two_tenant_jobs["job_b"]],
    )
    assert rows == []


async def test_call_jobs_null_tenant_row_invisible_without_bypass_sentinel(
    app_conn, two_tenant_jobs
):
    """A job recorded before a tenant was known (tenant_id IS NULL) is not
    visible under a real tenant context — NULL never equals a specific
    tenant value in SQL, so this falls out of the same USING clause as every
    other row, not a special case in the policy."""
    await _set_tenant(app_conn, str(two_tenant_jobs["tenant_a"]))
    row = await app_conn.fetchrow(
        "SELECT job_id FROM call_jobs WHERE job_id = $1", two_tenant_jobs["job_no_tenant"]
    )
    assert row is None


async def test_call_jobs_all_tenants_sentinel_sees_all_including_null_tenant(
    app_conn, two_tenant_jobs
):
    """services/worker and services/integration-service never see this
    table directly (Constraint #1/#2 — they go through the internal API,
    which always uses this same sentinel via get_internal_service_db) —
    this proves the sentinel path itself, matching production wiring."""
    await _set_tenant(app_conn, _ALL_TENANTS_SENTINEL)
    rows = await app_conn.fetch(
        "SELECT job_id FROM call_jobs WHERE job_id = ANY($1::text[])",
        [
            two_tenant_jobs["job_a"],
            two_tenant_jobs["job_b"],
            two_tenant_jobs["job_no_tenant"],
        ],
    )
    assert {r["job_id"] for r in rows} == {
        two_tenant_jobs["job_a"],
        two_tenant_jobs["job_b"],
        two_tenant_jobs["job_no_tenant"],
    }


async def test_call_jobs_concurrent_claim_from_separate_connections_only_one_wins(
    two_tenant_jobs,
):
    """The real atomicity guarantee (Constraint #10), proven the way it
    actually matters in production: two independent connections (standing
    in for two worker processes, each with its own connection — not one
    SQLAlchemy AsyncSession shared unsafely across coroutines, which is what
    services/api/tests/test_jobs.py's equivalent single-process test
    deliberately avoids) racing to claim the same row. Postgres's row-level
    locking on UPDATE is what decides the winner, not application code."""
    conn_1 = await _connect_or_skip(_APP_DSN)
    conn_2 = await _connect_or_skip(_APP_DSN)
    try:
        await _set_tenant(conn_1, _ALL_TENANTS_SENTINEL)
        await _set_tenant(conn_2, _ALL_TENANTS_SENTINEL)

        claim_sql = (
            "UPDATE call_jobs SET status = 'processing', attempts = attempts + 1 "
            "WHERE job_id = $1 AND status = 'queued' AND available_at <= now()"
        )
        import asyncio

        results = await asyncio.gather(
            conn_1.execute(claim_sql, two_tenant_jobs["job_a"]),
            conn_2.execute(claim_sql, two_tenant_jobs["job_a"]),
        )
        outcomes = sorted(results)
        assert outcomes == ["UPDATE 0", "UPDATE 1"]
    finally:
        await conn_1.close()
        await conn_2.close()
