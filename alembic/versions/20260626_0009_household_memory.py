"""stage 4i household memory entries

Revision ID: 20260626_0009
Revises: 20260626_0008
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260626_0009"
down_revision: str | None = "20260626_0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "household_memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_household_memory_entries_scope_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'deleted')",
            name="ck_household_memory_entries_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_household_memory_scope_status",
        "household_memory_entries",
        ["scope_type", "scope_chat_id", "status"],
    )
    op.create_index(
        "ix_household_memory_created_by_status",
        "household_memory_entries",
        ["created_by_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_household_memory_created_by_status",
        table_name="household_memory_entries",
    )
    op.drop_index("ix_household_memory_scope_status", table_name="household_memory_entries")
    op.drop_table("household_memory_entries")
