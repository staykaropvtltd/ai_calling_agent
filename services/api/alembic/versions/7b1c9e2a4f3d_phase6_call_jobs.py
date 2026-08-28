"""phase6 call_jobs — durable background job/event table

Revision ID: 7b1c9e2a4f3d
Revises: df467b3bdd3f
Create Date: 2026-08-27 12:00:00.000000

Phase 6 — adds the durable job/event record background processing needs.
Deliberately a NEW table, not a reuse of call_events (see models.py::CallJob
docstring) and a NEW migration rather than an edit to df467b3bdd3f (that
migration is applied history; RLS for a new table is layered on the same way
here, not by touching the old file).

The partial unique index on (provider_call_id, event_type) is the
authoritative idempotency guarantee for Phase 6: a duplicate webhook delivery
fails this constraint on INSERT rather than relying on an in-memory
check-then-set race. NULL provider_call_id is excluded from the constraint
(some event types may not be provider-call-scoped) so multiple such rows
don't collide with each other.

RLS follows df467b3bdd3f's exact pattern: grant staykaro_app, ENABLE + FORCE
ROW LEVEL SECURITY, one tenant_isolation policy comparing tenant_id against
current_setting('app.current_tenant', true), with the same __all_tenants__
bypass sentinel. tenant_id is nullable on this table (the "connected" event
is recorded before routing resolves a tenant), so a NULL-tenant row is
invisible under the policy to anything but the bypass sentinel — correct
fail-closed behavior, and consistent with only internal/worker code (which
always uses the bypass sentinel via get_internal_service_db) ever touching
this table in this phase.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7b1c9e2a4f3d"
down_revision: str | None = "df467b3bdd3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APP_ROLE = "staykaro_app"
_ALL_TENANTS_SENTINEL = "__all_tenants__"
_BYPASS = f"current_setting('app.current_tenant', true) = '{_ALL_TENANTS_SENTINEL}'"


def upgrade() -> None:
    op.create_table(
        "call_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("call_id", sa.String(length=36), nullable=True),
        sa.Column("provider_call_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'retrying')",
            name="ck_call_jobs_status",
        ),
        sa.ForeignKeyConstraint(["call_id"], ["calls.call_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "idx_call_jobs_status_available", "call_jobs", ["status", "available_at"], unique=False
    )
    op.create_index(
        "idx_call_jobs_tenant_status", "call_jobs", ["tenant_id", "status"], unique=False
    )
    op.create_index("idx_call_jobs_call_id", "call_jobs", ["call_id"], unique=False)
    op.create_index(
        "uq_call_jobs_provider_event",
        "call_jobs",
        ["provider_call_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("provider_call_id IS NOT NULL"),
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON call_jobs TO {_APP_ROLE}")
    op.execute("ALTER TABLE call_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON call_jobs
            USING ({_BYPASS} OR tenant_id = current_setting('app.current_tenant', true))
            WITH CHECK ({_BYPASS} OR tenant_id = current_setting('app.current_tenant', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON call_jobs")
    op.execute("ALTER TABLE call_jobs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE call_jobs DISABLE ROW LEVEL SECURITY")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON call_jobs FROM {_APP_ROLE}")
    op.drop_index("uq_call_jobs_provider_event", table_name="call_jobs")
    op.drop_index("idx_call_jobs_call_id", table_name="call_jobs")
    op.drop_index("idx_call_jobs_tenant_status", table_name="call_jobs")
    op.drop_index("idx_call_jobs_status_available", table_name="call_jobs")
    op.drop_table("call_jobs")
