"""stage 4g shopping lists and reminders

Revision ID: 20260626_0008
Revises: 20260626_0007
Create Date: 2026-06-26
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260626_0008"
down_revision: str | None = "20260626_0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.Text(), server_default="Список покупок", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_shopping_lists_scope_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_type", "scope_chat_id", name="uq_shopping_lists_scope"),
    )
    op.create_table(
        "shopping_list_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'done')",
            name="ck_shopping_list_items_status",
        ),
        sa.ForeignKeyConstraint(["list_id"], ["shopping_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_shopping_list_items_list_status",
        "shopping_list_items",
        ["list_id", "status"],
    )
    op.create_index(
        "ix_shopping_list_items_list_created",
        "shopping_list_items",
        ["list_id", "created_at"],
    )
    op.create_table(
        "reminders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_reminders_scope_type",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'sent', 'cancelled')",
            name="ck_reminders_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminders_status_remind_at", "reminders", ["status", "remind_at"])
    op.create_index(
        "ix_reminders_chat_status_remind_at",
        "reminders",
        ["chat_id", "status", "remind_at"],
    )
    op.create_index(
        "ix_reminders_user_status_remind_at",
        "reminders",
        ["user_id", "status", "remind_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reminders_user_status_remind_at", table_name="reminders")
    op.drop_index("ix_reminders_chat_status_remind_at", table_name="reminders")
    op.drop_index("ix_reminders_status_remind_at", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("ix_shopping_list_items_list_created", table_name="shopping_list_items")
    op.drop_index("ix_shopping_list_items_list_status", table_name="shopping_list_items")
    op.drop_table("shopping_list_items")
    op.drop_table("shopping_lists")
