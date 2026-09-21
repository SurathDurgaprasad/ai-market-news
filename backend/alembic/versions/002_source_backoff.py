"""Add source.consecutive_failures for scheduler backoff

Revision ID: 002_source_backoff
Revises: 001_initial_schema
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = "002_source_backoff"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("source", "consecutive_failures")
