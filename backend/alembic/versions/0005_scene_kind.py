"""Widen artifacts.kind for multi-instance content kinds (scene:{node_id}).

Revision ID: 0005_scene_kind
Revises: 0004_workspace
Create Date: 2025-01-05
"""
import sqlalchemy as sa

from alembic import op

revision = "0005_scene_kind"
down_revision = "0004_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 不支持 ALTER COLUMN，用 batch 模式重建表（语义等价，兼容 SQLite / Postgres）。
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column("kind", existing_type=sa.String(40), type_=sa.String(120), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column("kind", existing_type=sa.String(120), type_=sa.String(40), nullable=False)