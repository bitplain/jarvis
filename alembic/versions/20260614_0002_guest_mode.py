"""stage 2 guest mode

Revision ID: 20260614_0002
Revises: 20260614_0001
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260614_0002"
down_revision: str | None = "20260614_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    guest_status = postgresql.ENUM(
        "received",
        "answered",
        "failed",
        "ignored",
        name="guest_message_status",
        create_type=False,
    )
    guest_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "guest_messages_stub",
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("guest_query_id_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("caller_user_id_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("caller_chat_id_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("request_text", sa.Text(), server_default="", nullable=False),
    )
    op.add_column("guest_messages_stub", sa.Column("replied_text", sa.Text(), nullable=True))
    op.add_column("guest_messages_stub", sa.Column("response_text", sa.Text(), nullable=True))
    op.add_column("guest_messages_stub", sa.Column("provider", sa.String(length=64), nullable=True))
    op.add_column("guest_messages_stub", sa.Column("model", sa.String(length=255), nullable=True))
    op.add_column(
        "guest_messages_stub",
        sa.Column("status", guest_status, server_default="received", nullable=False),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("error_code", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "guest_messages_stub",
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_guest_messages_stub_telegram_update_id",
        "guest_messages_stub",
        ["telegram_update_id"],
    )
    op.create_index(
        "ix_guest_messages_stub_guest_query_id_hash",
        "guest_messages_stub",
        ["guest_query_id_hash"],
    )
    op.create_index(
        "ix_guest_messages_stub_caller_user_id_hash",
        "guest_messages_stub",
        ["caller_user_id_hash"],
    )
    op.create_index(
        "ix_guest_messages_stub_caller_chat_id_hash",
        "guest_messages_stub",
        ["caller_chat_id_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_guest_messages_stub_caller_chat_id_hash", table_name="guest_messages_stub")
    op.drop_index("ix_guest_messages_stub_caller_user_id_hash", table_name="guest_messages_stub")
    op.drop_index("ix_guest_messages_stub_guest_query_id_hash", table_name="guest_messages_stub")
    op.drop_index("ix_guest_messages_stub_telegram_update_id", table_name="guest_messages_stub")
    op.drop_column("guest_messages_stub", "answered_at")
    op.drop_column("guest_messages_stub", "error_code")
    op.drop_column("guest_messages_stub", "status")
    op.drop_column("guest_messages_stub", "model")
    op.drop_column("guest_messages_stub", "provider")
    op.drop_column("guest_messages_stub", "response_text")
    op.drop_column("guest_messages_stub", "replied_text")
    op.drop_column("guest_messages_stub", "request_text")
    op.drop_column("guest_messages_stub", "caller_chat_id_hash")
    op.drop_column("guest_messages_stub", "caller_user_id_hash")
    op.drop_column("guest_messages_stub", "guest_query_id_hash")
    op.drop_column("guest_messages_stub", "telegram_update_id")
    sa.Enum(name="guest_message_status").drop(op.get_bind(), checkfirst=True)
