"""nk07 tenant row level security

Revision ID: df467b3bdd3f
Revises: 228478a4578e
Create Date: 2026-08-26 15:11:21.053799

Database Design §6: a policy per tenant-scoped table comparing its tenant
column against the per-transaction session setting `app.current_tenant`,
set fresh via `SET LOCAL` (never plain `SET` — see src/tenant.py) on every
request. Fails CLOSED by design: an unset/empty setting matches no tenant_id
and satisfies no bypass clause, so it returns zero rows rather than every
row — a route that forgets to wire the tenant-context dependency looks
broken (empty results), not leaky. Only a request that deliberately sets the
sentinel `__all_tenants__` (super_admin, via src/tenant.py) sees across
tenants; there is no way to get that by simply doing nothing.

`FORCE ROW LEVEL SECURITY` is necessary but NOT sufficient: Postgres always
exempts superusers from RLS, FORCE or not, with no override. The bootstrap
role created by the official postgres image's POSTGRES_USER (staykaro_user
here) is a superuser — confirmed by hand against the dev container, where
the policies below silently restricted nothing until this role split was
added. Fix: a second, deliberately unprivileged `staykaro_app` role for the
app's actual runtime connection (DATABASE_URL after this migration);
staykaro_user remains superuser for migrations only, via the new
MIGRATION_DATABASE_URL (alembic/env.py falls back to DATABASE_URL if unset,
so this migration is a no-op change for anyone not using the new variable
yet — but RLS provides no real protection until they switch).

APP_DB_PASSWORD must be set wherever this migration runs against a real
database; SQL below reads it from the environment rather than accepting it
as a bind parameter because CREATE ROLE/ALTER ROLE do not support parameter
placeholders — this is operator-controlled deployment config, not user
input, so the same trust boundary as every other env-var-sourced secret in
this codebase applies.
"""
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'df467b3bdd3f'
down_revision: str | None = '228478a4578e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "staykaro_app"

# (table, SQL expression yielding the row's tenant id as text)
_TENANT_SCOPED_TABLES = [
    ("call_requests", "client_id::text"),
    ("admin_users", "tenant_id::text"),
    ("calls", "tenant_id"),
    ("call_turns", "tenant_id"),
    ("call_events", "tenant_id"),
    ("audit_logs", "tenant_id"),
]

# Tables the app queries but that aren't tenant-scoped rows themselves — no
# RLS policy, but staykaro_app still needs ordinary grants or every query
# against them 403s once it's no longer the (implicitly all-privileged)
# table owner. clients IS the tenant (super_admin-only routes manage it, at
# the application layer); phone_number_routes is telephony routing config.
_UNSCOPED_APP_TABLES = ["clients", "phone_number_routes"]

_ALL_TENANTS_SENTINEL = "__all_tenants__"
_BYPASS = f"current_setting('app.current_tenant', true) = '{_ALL_TENANTS_SENTINEL}'"


def _quote_literal(value: str) -> str:
    """Escape a value for safe interpolation into a SQL string literal.

    Doubles embedded single quotes per the SQL standard (equivalent to
    Postgres's quote_literal for this purpose) — sufficient here because the
    value is deployment config (an env var), not attacker-controlled input.
    """
    return value.replace("'", "''")


def upgrade() -> None:
    app_password = os.environ.get("APP_DB_PASSWORD", "")
    if not app_password:
        raise RuntimeError(
            "APP_DB_PASSWORD is not set — required to create the restricted "
            f"'{_APP_ROLE}' role that RLS actually protects. Without it, RLS "
            "policies would be created but silently bypassed by the migration "
            "role, exactly the gap this migration exists to close."
        )

    # app_password is deployment config (an env var), not request input, and
    # is quote-escaped above via _quote_literal — CREATE ROLE/ALTER ROLE don't
    # accept bind parameters, so string interpolation is the only option.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                CREATE ROLE {_APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS
                    PASSWORD '{_quote_literal(app_password)}';
            ELSE
                ALTER ROLE {_APP_ROLE} PASSWORD '{_quote_literal(app_password)}';
            END IF;
        END
        $$;
        """  # nosec B608
    )
    op.execute(f"GRANT CONNECT ON DATABASE {op.get_bind().engine.url.database} TO {_APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO {_APP_ROLE}"
    )

    for table in _UNSCOPED_APP_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_APP_ROLE}")

    for table, tenant_expr in _TENANT_SCOPED_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {_APP_ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING ({_BYPASS} OR {tenant_expr} = current_setting('app.current_tenant', true))
                WITH CHECK ({_BYPASS} OR {tenant_expr} = current_setting('app.current_tenant', true))
            """
        )


def downgrade() -> None:
    for table, _tenant_expr in reversed(_TENANT_SCOPED_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM {_APP_ROLE}")

    for table in reversed(_UNSCOPED_APP_TABLES):
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM {_APP_ROLE}")

    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE CONNECT ON DATABASE {op.get_bind().engine.url.database} FROM {_APP_ROLE}")
    # Role itself is intentionally not dropped — other sessions/pools may be
    # actively connected as it, and DROP ROLE fails while any are. Dropping
    # a login role is an explicit, separate operational decision.
