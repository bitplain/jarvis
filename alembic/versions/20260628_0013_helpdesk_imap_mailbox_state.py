"""hotfix helpdesk imap mailbox state

Revision ID: 20260628_0013
Revises: 20260627_0012
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260628_0013"
down_revision: str | None = "20260627_0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_imap_mailbox_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("folder", sa.Text(), nullable=False),
        sa.Column("uidvalidity", sa.Text(), nullable=True),
        sa.Column("last_seen_uid", sa.BigInteger(), nullable=True),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder", name="uq_helpdesk_imap_mailbox_state_folder"),
    )
    op.create_index(
        "ix_helpdesk_imap_mailbox_state_updated_at",
        "helpdesk_imap_mailbox_state",
        ["updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_helpdesk_imap_mailbox_state_updated_at",
        table_name="helpdesk_imap_mailbox_state",
    )
    op.drop_table("helpdesk_imap_mailbox_state")
