"""Prompt versioning: prompt_definitions / prompt_versions

Revision ID: 0002_prompt_versions
Revises: 0001_initial
Create Date: 2025-01-02
"""
import sqlalchemy as sa

from alembic import op

revision = "0002_prompt_versions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prompt_definitions_name", "prompt_definitions", ["name"], unique=True)

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt_definition_id", sa.String(36), sa.ForeignKey("prompt_definitions.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("model_preferences", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prompt_versions_prompt_definition_id", "prompt_versions", ["prompt_definition_id"])
    op.create_index(
        "uq_prompt_versions_definition_version",
        "prompt_versions",
        ["prompt_definition_id", "version_no"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("prompt_versions")
    op.drop_table("prompt_definitions")