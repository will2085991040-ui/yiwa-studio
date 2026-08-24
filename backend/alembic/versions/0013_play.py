"""PlaySession + PlayTurn: play_sessions + play_turns（Step 20 Play Runtime）。

Revision ID: 0013_play
Revises: 0012_material
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0013_play"
down_revision = "0012_material"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "play_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("world", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_play_sessions_project_id", "play_sessions", ["project_id"])
    op.create_table(
        "play_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("play_session_id", sa.String(36), sa.ForeignKey("play_sessions.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("intent", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("mutation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_play_turns_play_session_id", "play_turns", ["play_session_id"])


def downgrade() -> None:
    op.drop_index("ix_play_turns_play_session_id", table_name="play_turns")
    op.drop_table("play_turns")
    op.drop_index("ix_play_sessions_project_id", table_name="play_sessions")
    op.drop_table("play_sessions")