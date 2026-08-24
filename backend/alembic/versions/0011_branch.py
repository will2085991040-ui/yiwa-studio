"""Branch: branches + branch_versions（Step 18 分支一等公民）。

Revision ID: 0011_branch
Revises: 0010_skill
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0011_branch"
down_revision = "0010_skill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("parent_branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("plan", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("base_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("base_kind", sa.String(220), nullable=False, server_default="story_graph"),
        sa.Column("current_node_id", sa.String(80), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_branches_project_id", "branches", ["project_id"])
    op.create_table(
        "branch_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("branch_id", sa.String(36), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(220), nullable=False, server_default="story_graph"),
        sa.Column("content", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_branch_versions_branch_id", "branch_versions", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_branch_versions_branch_id", table_name="branch_versions")
    op.drop_table("branch_versions")
    op.drop_index("ix_branches_project_id", table_name="branches")
    op.drop_table("branches")