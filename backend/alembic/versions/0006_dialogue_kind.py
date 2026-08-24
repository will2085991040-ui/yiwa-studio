"""Widen artifacts.kind for dialogue content kinds (dialogue:{node_id}[:{choice_id}]).

dialogue:{node_id}[:{choice_id}] 最长 = 9 + 80 + 1 + 80 = 170 字符，超出 scene 阶段的 120，
故扩容到 220，覆盖「node_id(80) + ':' + choice_id(80)」上限。

Revision ID: 0006_dialogue_kind
Revises: 0005_scene_kind
Create Date: 2025-01-06
"""
import sqlalchemy as sa

from alembic import op

revision = "0006_dialogue_kind"
down_revision = "0005_scene_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 不支持 ALTER COLUMN，用 batch 模式重建表（语义等价）。
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column("kind", existing_type=sa.String(120), type_=sa.String(220), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch_op:
        batch_op.alter_column("kind", existing_type=sa.String(220), type_=sa.String(120), nullable=False)