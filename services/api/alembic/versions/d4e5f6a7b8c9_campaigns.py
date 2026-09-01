"""Phase 2 — campaigns and campaign_contacts tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-31

Creates two tables:
- campaigns: tenant-scoped outbound calling campaigns
- campaign_contacts: per-contact call tracking within a campaign

RLS tenant isolation: same pattern as call_requests and customers
(bypass for super_admin, tenant_id filter for everything else).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None

_JSONB_TYPE = JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("purpose", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="2"),
        sa.Column("retry_delay_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("total_contacts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("queued_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("no_answer_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("admin_users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'running', 'paused', 'completed', 'cancelled')",
            name="ck_campaigns_status",
        ),
    )
    op.create_index("idx_campaigns_client_id", "campaigns", ["client_id"])

    op.create_table(
        "campaign_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.String(36),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_data", _JSONB_TYPE, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "call_request_id",
            sa.Integer,
            sa.ForeignKey("call_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'dialing', 'completed', 'failed', 'no_answer', 'skipped')",
            name="ck_campaign_contacts_status",
        ),
    )
    op.create_index(
        "idx_campaign_contacts_campaign_id", "campaign_contacts", ["campaign_id"]
    )

    # RLS tenant isolation — same pattern as call_requests and customers.
    # A campaign's client_id must match the current session tenant for row-level
    # access. super_admin is detected by the __all_tenants__ sentinel value.
    # Campaigns don't have a tenant_id text column — client_id::text serves.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = 'campaigns' AND c.relrowsecurity
          ) THEN
            ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_policies WHERE tablename='campaigns' AND policyname='tenant_isolation'
          ) THEN
            CREATE POLICY tenant_isolation ON campaigns
              USING (
                current_setting('app.current_tenant', TRUE) = '__all_tenants__'
                OR client_id::text = current_setting('app.current_tenant', TRUE)
              )
              WITH CHECK (
                current_setting('app.current_tenant', TRUE) = '__all_tenants__'
                OR client_id::text = current_setting('app.current_tenant', TRUE)
              );
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("campaign_contacts")
    op.drop_table("campaigns")
