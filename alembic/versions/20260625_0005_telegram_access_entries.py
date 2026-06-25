"""stage 4f1 telegram access entries

Revision ID: 20260625_0005
Revises: 20260625_0004
Create Date: 2026-06-25
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260625_0005"
down_revision: str | None = "20260625_0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_access_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "entry_type IN ('user', 'group')",
            name="ck_telegram_access_entries_entry_type",
        ),
        sa.UniqueConstraint(
            "entry_type",
            "telegram_id",
            name="uq_telegram_access_entries_entry_type_telegram_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_access_entries")
