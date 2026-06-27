"""stage 4l helpdesk email events

Revision ID: 20260627_0012
Revises: 20260627_0011
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0012"
down_revision: str | None = "20260627_0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_email_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=True),
        sa.Column("imap_uid", sa.Text(), nullable=True),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("from_email_masked", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("glpi_ticket_id", sa.Text(), nullable=True),
        sa.Column("ticket_url", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.Text(), nullable=False),
        sa.Column("notify_status", sa.Text(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_helpdesk_email_events_message_id",
        "helpdesk_email_events",
        ["message_id"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_helpdesk_email_events_folder_imap_uid",
        "helpdesk_email_events",
        ["folder", "imap_uid"],
        unique=True,
        postgresql_where=sa.text("imap_uid IS NOT NULL"),
    )
    op.create_index(
        "ix_helpdesk_email_events_created_at",
        "helpdesk_email_events",
        ["created_at"],
    )
    op.create_index(
        "ix_helpdesk_email_events_notify_status",
        "helpdesk_email_events",
        ["notify_status"],
    )
    op.create_index(
        "ix_helpdesk_email_events_glpi_ticket_id",
        "helpdesk_email_events",
        ["glpi_ticket_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_helpdesk_email_events_glpi_ticket_id", table_name="helpdesk_email_events")
    op.drop_index("ix_helpdesk_email_events_notify_status", table_name="helpdesk_email_events")
    op.drop_index("ix_helpdesk_email_events_created_at", table_name="helpdesk_email_events")
    op.drop_index("uq_helpdesk_email_events_folder_imap_uid", table_name="helpdesk_email_events")
    op.drop_index("uq_helpdesk_email_events_message_id", table_name="helpdesk_email_events")
    op.drop_table("helpdesk_email_events")
