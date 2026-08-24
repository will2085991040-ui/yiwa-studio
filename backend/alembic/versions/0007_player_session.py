"""PlayerSession persistence: player_sessions（Step 13 互动游玩会话）。

Revision ID: 0007_player_session
Revises: 0006_dialogue_kind
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0007_player_session"
down_revision = "0006_dialogue_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "player_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("current_node_id", sa.String(80), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_player_sessions_project_id", "player_sessions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_player_sessions_project_id", table_name="player_sessions")
    op.drop_table("player_sessions")