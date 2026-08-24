"""ActionProposal: action_proposals（Step 16 HITL 提议持久化）。

Revision ID: 0009_action_proposal
Revises: 0008_memory_entry
Create Date: 2025-01-07
"""
import sqlalchemy as sa

from alembic import op

revision = "0009_action_proposal"
down_revision = "0008_memory_entry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(220), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("risk", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("node_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_action_proposals_project_id", "action_proposals", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_action_proposals_project_id", table_name="action_proposals")
    op.drop_table("action_proposals")