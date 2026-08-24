"""MemoryEntry: memory_entries（Step 15 基础记忆的可重建索引表）。

Revision ID: 0008_memory_entry
Revises: 0007_player_session
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0008_memory_entry"
down_revision = "0007_player_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("ref_kind", sa.String(220), nullable=False, server_default=""),
        sa.Column("ref_id", sa.String(220), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_entries_project_id", "memory_entries", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_entries_project_id", table_name="memory_entries")
    op.drop_table("memory_entries")