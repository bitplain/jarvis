"""stage 4k web search cache

Revision ID: 20260627_0011
Revises: 20260627_0010
Create Date: 2026-06-27
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260627_0011"
down_revision: str | None = "20260627_0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "web_search_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "query_hash",
            name="uq_web_search_cache_provider_query_hash",
        ),
    )
    op.create_index("ix_web_search_cache_expires_at", "web_search_cache", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_web_search_cache_expires_at", table_name="web_search_cache")
    op.drop_table("web_search_cache")
