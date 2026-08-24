"""Interactive creation layer: project workspace + artifact versioning

Revision ID: 0004_workspace
Revises: 0003_artifacts
Create Date: 2025-01-04
"""
import sqlalchemy as sa

from alembic import op

revision = "0004_workspace"
down_revision = "0003_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # StoryProject 增强：用户可见标题 / 描述 / 整体版本
    op.add_column("projects", sa.Column("title", sa.String(200), nullable=False, server_default=""))
    op.add_column("projects", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"))

    # Artifact 版本体系：Git 式追踪（旧版本不覆盖）
    op.add_column("artifacts", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("artifacts", sa.Column("parent_version", sa.Integer(), nullable=True))
    op.add_column("artifacts", sa.Column("source", sa.String(20), nullable=False, server_default="agent"))
    op.add_column("artifacts", sa.Column("change_reason", sa.Text(), nullable=True))
    op.add_column("artifacts", sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("artifacts", "is_latest")
    op.drop_column("artifacts", "change_reason")
    op.drop_column("artifacts", "source")
    op.drop_column("artifacts", "parent_version")
    op.drop_column("artifacts", "version")
    op.drop_column("projects", "current_version")
    op.drop_column("projects", "description")
    op.drop_column("projects", "title")