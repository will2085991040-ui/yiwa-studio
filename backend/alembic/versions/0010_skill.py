"""Skill: skills（Step 17 技能系统）。

Revision ID: 0010_skill
Revises: 0009_action_proposal
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0010_skill"
down_revision = "0009_action_proposal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(20), nullable=False, server_default="system"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_skills_project_id", "skills", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_skills_project_id", table_name="skills")
    op.drop_table("skills")