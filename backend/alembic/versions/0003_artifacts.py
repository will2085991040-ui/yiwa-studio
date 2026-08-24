"""Artifact persistence: artifacts

Revision ID: 0003_artifacts
Revises: 0002_prompt_versions
Create Date: 2025-01-03
"""
import sqlalchemy as sa

from alembic import op

revision = "0003_artifacts"
down_revision = "0002_prompt_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("task_id", sa.String(80), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_project_id", table_name="artifacts")
    op.drop_table("artifacts")