"""stage 1a 2a event items foundation

Revision ID: 20260629_0016
Revises: 20260629_0015
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260629_0016"
down_revision: str | None = "20260629_0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "event_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("card_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('personal', 'household', 'work', 'system')",
            name="ck_event_items_scope",
        ),
        sa.CheckConstraint(
            "status IN ('new', 'seen', 'done', 'snoozed', 'archived', 'failed')",
            name="ck_event_items_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'critical')",
            name="ck_event_items_priority",
        ),
        sa.CheckConstraint(
            (
                "event_type IN ('reminder', 'note', 'shopping', 'helpdesk_ticket', "
                "'whoop_sleep', 'system_alert', 'digest_item')"
            ),
            name="ck_event_items_event_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_items_user_id", "event_items", ["user_id"])
    op.create_index("ix_event_items_chat_id", "event_items", ["chat_id"])
    op.create_index(
        "ix_event_items_scope_status_priority_due",
        "event_items",
        ["scope", "status", "priority", "due_at"],
    )
    op.create_index(
        "ix_event_items_user_scope_status",
        "event_items",
        ["user_id", "scope", "status"],
    )
    op.create_index(
        "ix_event_items_chat_scope_status",
        "event_items",
        ["chat_id", "scope", "status"],
    )
    op.create_index("ix_event_items_created_at", "event_items", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_event_items_created_at", table_name="event_items")
    op.drop_index("ix_event_items_chat_scope_status", table_name="event_items")
    op.drop_index("ix_event_items_user_scope_status", table_name="event_items")
    op.drop_index("ix_event_items_scope_status_priority_due", table_name="event_items")
    op.drop_index("ix_event_items_chat_id", table_name="event_items")
    op.drop_index("ix_event_items_user_id", table_name="event_items")
    op.drop_table("event_items")
