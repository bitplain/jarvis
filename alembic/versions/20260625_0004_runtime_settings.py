"""stage 4d runtime provider settings

Revision ID: 20260625_0004
Revises: 20260614_0003
Create Date: 2026-06-25
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260625_0004"
down_revision: str | None = "20260614_0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_telegram_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("runtime_settings")
