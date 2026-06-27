"""stage 4j daily brief and shopping v2

Revision ID: 20260627_0010
Revises: 20260626_0009
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0010"
down_revision: str | None = "20260626_0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("shopping_list_items", sa.Column("quantity", sa.Numeric(10, 3), nullable=True))
    op.add_column("shopping_list_items", sa.Column("unit", sa.Text(), nullable=True))
    op.add_column("shopping_list_items", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("shopping_list_items", sa.Column("category", sa.Text(), nullable=True))
    op.create_table(
        "daily_brief_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("send_time", sa.String(length=5), server_default="09:00", nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Europe/Moscow", nullable=False),
        sa.Column("last_sent_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('private', 'group')",
            name="ck_daily_brief_settings_scope_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_daily_brief_settings_private_scope",
        "daily_brief_settings",
        ["scope_type", "chat_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_daily_brief_settings_group_scope",
        "daily_brief_settings",
        ["scope_type", "chat_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_daily_brief_settings_group_scope", table_name="daily_brief_settings")
    op.drop_index("uq_daily_brief_settings_private_scope", table_name="daily_brief_settings")
    op.drop_table("daily_brief_settings")
    op.drop_column("shopping_list_items", "category")
    op.drop_column("shopping_list_items", "note")
    op.drop_column("shopping_list_items", "unit")
    op.drop_column("shopping_list_items", "quantity")
