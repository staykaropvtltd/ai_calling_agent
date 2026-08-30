"""Phase 1 — call state machine, customer entity, simulation flag

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30

Implements the Phase 1 data model:

1.  ``customers`` table — deduplicated per-tenant contact/customer records.
    Each (client_id, phone) pair is unique within a tenant; this is the basis
    for the upsert-by-phone semantics in the client router.  RLS added here
    using the same pattern as call_requests (client_id::text).

2.  ``call_requests`` new columns — proper lifecycle status, simulation flag,
    customer FK, connection status, and failure reason.  Existing rows are
    set to ``status='pending'`` / ``connection_status='not_attempted'`` /
    ``is_simulation=false`` — all truthful: pre-Phase-1 rows were created by
    POST /call but no outbound dialler existed, so their actual fate is
    unknown.

3.  ``calls`` new columns — is_simulation, connection_status, optional FK to
    the call_requests work-item that triggered the session.  Existing rows
    (all created by the voice gateway for live inbound calls) receive
    ``connection_status='connected'`` by default.

4.  ``calls.status`` CHECK constraint extended to include ``no_answer``,
    ``voicemail``, and ``cancelled`` — values that the fixed
    ``finalize_call`` endpoint in routers/internal.py can now produce.

Downgrade notes
---------------
* Dropping ``call_requests.status`` / ``calls.status`` new-value rows
  requires a data conversion step.  The downgrade handles this by mapping
  ``no_answer`` → ``failed``, ``voicemail`` → ``failed``,
  ``cancelled`` → ``failed`` on ``calls`` before restoring the narrower
  constraint.  This is intentionally lossy — only run the downgrade against
  dev data, never against a database with real call records.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "staykaro_app"
_ALL_TENANTS_SENTINEL = "__all_tenants__"
_BYPASS = f"current_setting('app.current_tenant', true) = '{_ALL_TENANTS_SENTINEL}'"


def upgrade() -> None:
    # ── 1. Create customers table ──────────────────────────────────────────────
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("language_code", sa.String(10), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("metadata_json", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("idx_customers_client_id", "customers", ["client_id"])
    op.create_index(
        "uq_customers_client_phone",
        "customers",
        ["client_id", "phone"],
        unique=True,
    )

    # RLS for customers — same pattern as call_requests in df467b3bdd3f
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO {_APP_ROLE}")
    op.execute("ALTER TABLE customers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customers FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON customers
            USING ({_BYPASS} OR client_id::text = current_setting('app.current_tenant', true))
            WITH CHECK ({_BYPASS} OR client_id::text = current_setting('app.current_tenant', true))
        """
    )

    # ── 2. Alter call_requests ─────────────────────────────────────────────────

    # status — pending | queued | dialing | ringing | connected | in_progress |
    #          completed | failed | cancelled | no_answer | voicemail
    op.add_column("call_requests", sa.Column("status", sa.String(30), nullable=True))
    op.execute("UPDATE call_requests SET status = 'pending' WHERE status IS NULL")
    op.alter_column("call_requests", "status", nullable=False, server_default="pending")
    op.create_check_constraint(
        "ck_call_requests_status",
        "call_requests",
        "status IN ('pending', 'queued', 'dialing', 'ringing', 'connected', "
        "'in_progress', 'completed', 'failed', 'cancelled', 'no_answer', 'voicemail')",
    )

    # call_type — outbound | inbound
    op.add_column("call_requests", sa.Column("call_type", sa.String(20), nullable=True))
    op.execute("UPDATE call_requests SET call_type = 'outbound' WHERE call_type IS NULL")
    op.alter_column("call_requests", "call_type", nullable=False, server_default="outbound")
    op.create_check_constraint(
        "ck_call_requests_call_type",
        "call_requests",
        "call_type IN ('inbound', 'outbound')",
    )

    # is_simulation — false for all pre-Phase-1 rows (they were real-intent requests)
    op.add_column(
        "call_requests",
        sa.Column("is_simulation", sa.Boolean, nullable=True),
    )
    op.execute("UPDATE call_requests SET is_simulation = false WHERE is_simulation IS NULL")
    op.alter_column("call_requests", "is_simulation", nullable=False, server_default=sa.false())

    # customer_id — nullable FK; NULL for all pre-Phase-1 rows
    op.add_column(
        "call_requests",
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # telephony_call_id — logical reference to calls.call_id; nullable
    op.add_column("call_requests", sa.Column("telephony_call_id", sa.String(36), nullable=True))

    # connection_status — not_attempted | attempted | connected | failed_pre_connect
    op.add_column("call_requests", sa.Column("connection_status", sa.String(30), nullable=True))
    op.execute(
        "UPDATE call_requests SET connection_status = 'not_attempted' "
        "WHERE connection_status IS NULL"
    )
    op.alter_column(
        "call_requests", "connection_status", nullable=False, server_default="not_attempted"
    )
    op.create_check_constraint(
        "ck_call_requests_connection_status",
        "call_requests",
        "connection_status IN ('not_attempted', 'attempted', 'connected', 'failed_pre_connect')",
    )

    # failure_reason — nullable; values set by finalize logic
    op.add_column("call_requests", sa.Column("failure_reason", sa.String(50), nullable=True))

    # Remaining Phase 1 columns — all nullable
    op.add_column("call_requests", sa.Column("duration_seconds", sa.Integer, nullable=True))
    op.add_column("call_requests", sa.Column("recording_url", sa.Text, nullable=True))
    op.add_column("call_requests", sa.Column("notes", sa.Text, nullable=True))
    op.add_column("call_requests", sa.Column("outcome", sa.String(50), nullable=True))

    # ── 3. Alter calls ─────────────────────────────────────────────────────────

    # is_simulation — false for all pre-Phase-1 rows
    op.add_column("calls", sa.Column("is_simulation", sa.Boolean, nullable=True))
    op.execute("UPDATE calls SET is_simulation = false WHERE is_simulation IS NULL")
    op.alter_column("calls", "is_simulation", nullable=False, server_default=sa.false())

    # connection_status — pre-Phase-1 rows were all live inbound calls → connected
    op.add_column("calls", sa.Column("connection_status", sa.String(30), nullable=True))
    op.execute("UPDATE calls SET connection_status = 'connected' WHERE connection_status IS NULL")
    op.alter_column("calls", "connection_status", nullable=False, server_default="connected")
    op.create_check_constraint(
        "ck_calls_connection_status",
        "calls",
        "connection_status IN ('not_attempted', 'attempted', 'connected', 'failed_pre_connect')",
    )

    # call_request_id — nullable back-reference to the work-item
    op.add_column(
        "calls",
        sa.Column(
            "call_request_id",
            sa.Integer,
            sa.ForeignKey("call_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Extend the existing ck_calls_status constraint to include new terminal states
    op.drop_constraint("ck_calls_status", "calls", type_="check")
    op.create_check_constraint(
        "ck_calls_status",
        "calls",
        "status IN ('active', 'completed', 'failed', 'no_answer', 'voicemail', 'cancelled')",
    )

    # Grant staykaro_app on call_jobs as well if not already granted (idempotent check)
    # call_jobs was created in 7b1c9e2a4f3d — grants may have been applied there.
    # The DO block makes this safe to re-run.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'call_jobs'
            ) THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON call_jobs TO {_APP_ROLE}';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Restore the original 3-value calls.status constraint.
    # Any rows with new-state values are mapped to 'failed' — this is lossy,
    # so ONLY run this downgrade against dev/test databases.
    op.execute(
        "UPDATE calls SET status = 'failed' "
        "WHERE status IN ('no_answer', 'voicemail', 'cancelled')"
    )
    op.drop_constraint("ck_calls_status", "calls", type_="check")
    op.create_check_constraint(
        "ck_calls_status",
        "calls",
        "status IN ('active', 'completed', 'failed')",
    )

    # Remove calls Phase 1 columns
    op.drop_column("calls", "call_request_id")
    op.drop_constraint("ck_calls_connection_status", "calls", type_="check")
    op.drop_column("calls", "connection_status")
    op.drop_column("calls", "is_simulation")

    # Remove call_requests Phase 1 columns
    for col in [
        "outcome",
        "notes",
        "recording_url",
        "duration_seconds",
        "failure_reason",
    ]:
        op.drop_column("call_requests", col)

    op.drop_constraint("ck_call_requests_connection_status", "call_requests", type_="check")
    op.drop_column("call_requests", "connection_status")
    op.drop_column("call_requests", "telephony_call_id")
    op.drop_column("call_requests", "customer_id")
    op.drop_column("call_requests", "is_simulation")
    op.drop_constraint("ck_call_requests_call_type", "call_requests", type_="check")
    op.drop_column("call_requests", "call_type")
    op.drop_constraint("ck_call_requests_status", "call_requests", type_="check")
    op.drop_column("call_requests", "status")

    # Remove customers table (drops FK from call_requests.customer_id automatically)
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON customers")
    op.execute("ALTER TABLE customers NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customers DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON customers FROM {_APP_ROLE}")
    op.drop_index("uq_customers_client_phone", table_name="customers")
    op.drop_index("idx_customers_client_id", table_name="customers")
    op.drop_table("customers")
