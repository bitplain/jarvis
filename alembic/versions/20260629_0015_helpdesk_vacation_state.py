"""stage 4l3 helpdesk vacation state

Revision ID: 20260629_0015
Revises: 20260629_0014
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260629_0015"
down_revision: str | None = "20260629_0014"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_vacation_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default="default"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("disabled_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", name="uq_helpdesk_vacation_state_scope"),
    )
    op.create_index(
        "ix_helpdesk_vacation_state_updated_at",
        "helpdesk_vacation_state",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_helpdesk_vacation_state_updated_at",
        table_name="helpdesk_vacation_state",
    )
    op.drop_table("helpdesk_vacation_state")
