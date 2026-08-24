"""Phase 0 initial schema: projects / agent_specs / agent_versions / agent_runs / agent_steps

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01
"""
import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("template", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_specs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("goal_summary", sa.String(200), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("policies", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_specs_project_id", "agent_specs", ["project_id"])
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_spec_id", sa.String(36), sa.ForeignKey("agent_specs.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("spec_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_versions_agent_spec_id", "agent_versions", ["agent_spec_id"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_agent_version_id", "agent_runs", ["agent_version_id"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_run_id", sa.String(36), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("agent", sa.String(40), nullable=False),
        sa.Column("step_key", sa.String(80), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ok"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_steps_agent_run_id", "agent_steps", ["agent_run_id"])


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
    op.drop_table("agent_versions")
    op.drop_table("agent_specs")
    op.drop_table("projects")
