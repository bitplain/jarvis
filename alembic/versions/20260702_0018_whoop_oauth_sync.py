"""stage 4 whoop oauth sync foundation

Revision ID: 20260702_0018
Revises: 20260701_0017
Create Date: 2026-07-02
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260702_0018"
down_revision: str | None = "20260701_0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "whoop_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.Text(), server_default="", nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whoop_user_id", sa.BigInteger(), nullable=True),
        sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('not_connected', 'connected', 'error', 'revoked')",
            name="ck_whoop_integrations_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "telegram_user_id",
            name="uq_whoop_integrations_telegram_user_id",
        ),
    )
    op.create_index(
        "ix_whoop_integrations_user_id",
        "whoop_integrations",
        ["user_id"],
    )
    op.create_index("ix_whoop_integrations_status", "whoop_integrations", ["status"])
    op.create_index(
        "ix_whoop_integrations_last_sync",
        "whoop_integrations",
        ["last_sync_at"],
    )

    op.create_table(
        "whoop_sleep_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("whoop_sleep_id", sa.Text(), nullable=False),
        sa.Column("cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone_offset", sa.Text(), nullable=False),
        sa.Column("nap", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("score_state", sa.Text(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["whoop_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "whoop_sleep_id",
            name="uq_whoop_sleep_records_integration_sleep",
        ),
    )
    op.create_index("ix_whoop_sleep_records_user_id", "whoop_sleep_records", ["user_id"])
    op.create_index(
        "ix_whoop_sleep_records_start_at",
        "whoop_sleep_records",
        ["start_at"],
    )

    op.create_table(
        "whoop_recovery_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("score_state", sa.Text(), nullable=True),
        sa.Column("recovery_score", sa.Integer(), nullable=True),
        sa.Column("hrv_rmssd_milli", sa.Numeric(12, 6), nullable=True),
        sa.Column("resting_heart_rate", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["whoop_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "cycle_id",
            name="uq_whoop_recovery_records_integration_cycle",
        ),
    )
    op.create_index("ix_whoop_recovery_records_user_id", "whoop_recovery_records", ["user_id"])
    op.create_index(
        "ix_whoop_recovery_records_cycle_id",
        "whoop_recovery_records",
        ["cycle_id"],
    )

    op.create_table(
        "whoop_cycle_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("cycle_id", sa.BigInteger(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone_offset", sa.Text(), nullable=False),
        sa.Column("score_state", sa.Text(), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["whoop_integrations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "integration_id",
            "cycle_id",
            name="uq_whoop_cycle_records_integration_cycle",
        ),
    )
    op.create_index("ix_whoop_cycle_records_user_id", "whoop_cycle_records", ["user_id"])
    op.create_index("ix_whoop_cycle_records_start_at", "whoop_cycle_records", ["start_at"])


def downgrade() -> None:
    op.drop_index("ix_whoop_cycle_records_start_at", table_name="whoop_cycle_records")
    op.drop_index("ix_whoop_cycle_records_user_id", table_name="whoop_cycle_records")
    op.drop_table("whoop_cycle_records")
    op.drop_index("ix_whoop_recovery_records_cycle_id", table_name="whoop_recovery_records")
    op.drop_index("ix_whoop_recovery_records_user_id", table_name="whoop_recovery_records")
    op.drop_table("whoop_recovery_records")
    op.drop_index("ix_whoop_sleep_records_start_at", table_name="whoop_sleep_records")
    op.drop_index("ix_whoop_sleep_records_user_id", table_name="whoop_sleep_records")
    op.drop_table("whoop_sleep_records")
    op.drop_index("ix_whoop_integrations_last_sync", table_name="whoop_integrations")
    op.drop_index("ix_whoop_integrations_status", table_name="whoop_integrations")
    op.drop_index("ix_whoop_integrations_user_id", table_name="whoop_integrations")
    op.drop_table("whoop_integrations")
