"""stage 3a business mode foundation

Revision ID: 20260614_0003
Revises: 20260614_0002
Create Date: 2026-06-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260614_0003"
down_revision: str | None = "20260614_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    connection_status = postgresql.ENUM(
        "enabled",
        "disabled",
        "ignored",
        "failed",
        name="business_connection_status",
        create_type=False,
    )
    message_direction = postgresql.ENUM(
        "incoming",
        "outgoing",
        "edited",
        "deleted",
        name="business_message_direction",
        create_type=False,
    )
    message_status = postgresql.ENUM(
        "received",
        "ignored",
        "queued",
        "answered",
        "failed",
        "deleted",
        "edited",
        name="business_message_status",
        create_type=False,
    )
    connection_status.create(op.get_bind(), checkfirst=True)
    message_direction.create(op.get_bind(), checkfirst=True)
    message_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "business_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_connection_id", sa.String(length=255), nullable=False),
        sa.Column("business_user_id", sa.BigInteger(), nullable=True),
        sa.Column("user_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("can_reply", sa.Boolean(), nullable=False),
        sa.Column("can_read_messages", sa.Boolean(), nullable=False),
        sa.Column("rights_json", postgresql.JSONB(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", connection_status, nullable=False),
    )
    op.create_index(
        "ix_business_connections_business_connection_id",
        "business_connections",
        ["business_connection_id"],
        unique=True,
    )
    op.create_index(
        "ix_business_connections_business_user_id",
        "business_connections",
        ["business_user_id"],
    )
    op.create_index(
        "ix_business_connections_user_chat_id",
        "business_connections",
        ["user_chat_id"],
    )

    op.create_table(
        "business_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_connection_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("from_user_id", sa.BigInteger(), nullable=True),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", sa.Integer(), nullable=True),
        sa.Column("status", message_status, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_business_messages_business_connection_id",
        "business_messages",
        ["business_connection_id"],
    )
    op.create_index(
        "ix_business_messages_telegram_message_id",
        "business_messages",
        ["telegram_message_id"],
    )
    op.create_index("ix_business_messages_chat_id", "business_messages", ["chat_id"])
    op.create_index("ix_business_messages_from_user_id", "business_messages", ["from_user_id"])
    op.create_index(
        "ix_business_messages_connection_chat_created",
        "business_messages",
        ["business_connection_id", "chat_id", "created_at"],
    )
    op.create_index(
        "ix_business_messages_lookup",
        "business_messages",
        ["business_connection_id", "chat_id", "telegram_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_business_messages_lookup", table_name="business_messages")
    op.drop_index("ix_business_messages_connection_chat_created", table_name="business_messages")
    op.drop_index("ix_business_messages_from_user_id", table_name="business_messages")
    op.drop_index("ix_business_messages_chat_id", table_name="business_messages")
    op.drop_index("ix_business_messages_telegram_message_id", table_name="business_messages")
    op.drop_index("ix_business_messages_business_connection_id", table_name="business_messages")
    op.drop_table("business_messages")
    op.drop_index("ix_business_connections_user_chat_id", table_name="business_connections")
    op.drop_index("ix_business_connections_business_user_id", table_name="business_connections")
    op.drop_index(
        "ix_business_connections_business_connection_id",
        table_name="business_connections",
    )
    op.drop_table("business_connections")
    sa.Enum(name="business_message_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="business_message_direction").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="business_connection_status").drop(op.get_bind(), checkfirst=True)
