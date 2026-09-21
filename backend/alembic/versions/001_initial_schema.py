"""Initial schema — canonical event model with entities and event_time

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-18

Changes from original baseline:
- Added Event.entities (JSON) — stores LLM-extracted organizations/products/people
- Added Event.event_time (DateTime) — when the underlying event occurred (source pub time)
- Removed Event.why_it_matters (Text) — PRD explicitly forbids editorial commentary
- Article.published_at is now correctly populated from source RSS feeds
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Organization ──────────────────────────────────────────────────────────
    op.create_table(
        "organization",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_organization_name", "organization", ["name"])

    # ── Source ────────────────────────────────────────────────────────────────
    op.create_table(
        "source",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("tier", sa.String(), nullable=True),
        sa.Column("polling_tier", sa.String(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("health_status", sa.String(), nullable=True),
        sa.Column("last_error_info", sa.String(), nullable=True),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )

    # ── Article ───────────────────────────────────────────────────────────────
    op.create_table(
        "article",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("body_excerpt", sa.String(500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("hash", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["source.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url"),
    )
    op.create_index("ix_article_hash", "article", ["hash"])

    # ── Event ─────────────────────────────────────────────────────────────────
    # NOTE: embedding column is omitted for PostgreSQL-only pgvector deployments.
    # Add it manually if using pgvector: ALTER TABLE event ADD COLUMN embedding vector(1536);
    op.create_table(
        "event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("headline", sa.String(), nullable=False),
        sa.Column("short_summary", sa.String(), nullable=False),
        sa.Column("what_changed", sa.Text(), nullable=True),
        # NOTE: why_it_matters intentionally omitted — PRD forbids editorial commentary
        sa.Column("importance_score", sa.Integer(), nullable=True),
        sa.Column("importance_reasoning", sa.JSON(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("article_url", sa.String(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=True),  # Override with vector(1536) for pgvector
        sa.Column("primary_source_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["primary_source_id"], ["source.id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["event.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── EventArticle ──────────────────────────────────────────────────────────
    op.create_table(
        "eventarticle",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("link_type", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["article.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"]),
        sa.PrimaryKeyConstraint("event_id", "article_id"),
    )


def downgrade() -> None:
    op.drop_table("eventarticle")
    op.drop_table("event")
    op.drop_index("ix_article_hash", table_name="article")
    op.drop_table("article")
    op.drop_table("source")
    op.drop_index("ix_organization_name", table_name="organization")
    op.drop_table("organization")
