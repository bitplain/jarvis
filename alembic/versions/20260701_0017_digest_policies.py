"""stage 3 event inbox digest policies

Revision ID: 20260701_0017
Revises: 20260629_0016
Create Date: 2026-07-01
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260701_0017"
down_revision: str | None = "20260629_0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "digest_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "scope_filter_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("send_time", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default="Europe/Moscow", nullable=False),
        sa.Column("target_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("last_sent_date", sa.Date(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_digest_policies_key"),
    )
    op.create_index("ix_digest_policies_enabled", "digest_policies", ["enabled"])
    op.create_index("ix_digest_policies_send_time", "digest_policies", ["send_time"])

    digest_policies = sa.table(
        "digest_policies",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("key", sa.Text()),
        sa.column("title", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("scope_filter_json", postgresql.JSONB(astext_type=sa.Text())),
        sa.column("send_time", sa.Text()),
        sa.column("timezone", sa.Text()),
        sa.column("target_chat_id", sa.BigInteger()),
        sa.column("last_sent_date", sa.Date()),
        sa.column("last_sent_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime(2026, 7, 1, tzinfo=UTC)
    op.bulk_insert(
        digest_policies,
        [
            {
                "id": "00000000-0000-4000-8000-000000000301",
                "key": "personal_morning",
                "title": "Личный утренний дайджест",
                "enabled": True,
                "scope_filter_json": {"scopes": ["personal", "household"]},
                "send_time": "06:50",
                "timezone": "Europe/Moscow",
                "target_chat_id": None,
                "last_sent_date": None,
                "last_sent_at": None,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": "00000000-0000-4000-8000-000000000302",
                "key": "work_start",
                "title": "Рабочий дайджест",
                "enabled": True,
                "scope_filter_json": {"scopes": ["work"]},
                "send_time": "09:00",
                "timezone": "Europe/Moscow",
                "target_chat_id": None,
                "last_sent_date": None,
                "last_sent_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_digest_policies_send_time", table_name="digest_policies")
    op.drop_index("ix_digest_policies_enabled", table_name="digest_policies")
    op.drop_table("digest_policies")
