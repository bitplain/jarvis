"""stage 4l2 helpdesk ticket work items

Revision ID: 20260629_0014
Revises: 20260628_0013
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260629_0014"
down_revision: str | None = "20260628_0013"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_ticket_work_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("glpi_ticket_id", sa.Text(), nullable=False),
        sa.Column("latest_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("assigned_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('waiting_ack', 'in_work', 'done', 'dismissed')",
            name="ck_helpdesk_ticket_work_items_status",
        ),
        sa.ForeignKeyConstraint(
            ["latest_event_id"],
            ["helpdesk_email_events.id"],
            name="fk_helpdesk_ticket_work_items_latest_event",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "glpi_ticket_id",
            "telegram_chat_id",
            name="uq_helpdesk_ticket_work_items_ticket_chat",
        ),
    )
    op.create_index(
        "ix_helpdesk_ticket_work_items_status_next",
        "helpdesk_ticket_work_items",
        ["status", "next_reminder_at"],
    )
    op.create_index(
        "ix_helpdesk_ticket_work_items_chat_status",
        "helpdesk_ticket_work_items",
        ["telegram_chat_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_helpdesk_ticket_work_items_chat_status",
        table_name="helpdesk_ticket_work_items",
    )
    op.drop_index(
        "ix_helpdesk_ticket_work_items_status_next",
        table_name="helpdesk_ticket_work_items",
    )
    op.drop_table("helpdesk_ticket_work_items")
