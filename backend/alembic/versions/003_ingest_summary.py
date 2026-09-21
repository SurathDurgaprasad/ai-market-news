"""Add source.last_ingest_summary for scheduler observability.

Revision ID: 003_ingest_summary
Revises: 002_source_backoff
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = "003_ingest_summary"
down_revision = "002_source_backoff"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source", sa.Column("last_ingest_summary", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("source", "last_ingest_summary")
