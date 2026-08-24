"""Material: materials（Step 19 素材元数据与引用）。

Revision ID: 0012_material
Revises: 0011_branch
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0012_material"
down_revision = "0011_branch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("storage_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("ref_kind", sa.String(220), nullable=False, server_default=""),
        sa.Column("ref_id", sa.String(220), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_materials_project_id", "materials", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_materials_project_id", table_name="materials")
    op.drop_table("materials")