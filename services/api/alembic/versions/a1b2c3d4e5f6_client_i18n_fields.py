"""client i18n fields — country, timezone, currency, language, phone_country_code

Revision ID: a1b2c3d4e5f6
Revises: 7b1c9e2a4f3d
Create Date: 2026-08-30 13:00:00.000000

Adds internationalisation fields to the clients table so the platform can
serve clients worldwide (UAE, India, etc.) without hard-coding geography.
All columns are nullable so existing rows remain valid after the migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7b1c9e2a4f3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("country", sa.String(2), nullable=True))
    op.add_column("clients", sa.Column("timezone", sa.String(100), nullable=True))
    op.add_column("clients", sa.Column("currency", sa.String(3), nullable=True))
    op.add_column("clients", sa.Column("default_language", sa.String(10), nullable=True))
    op.add_column("clients", sa.Column("phone_country_code", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "phone_country_code")
    op.drop_column("clients", "default_language")
    op.drop_column("clients", "currency")
    op.drop_column("clients", "timezone")
    op.drop_column("clients", "country")
