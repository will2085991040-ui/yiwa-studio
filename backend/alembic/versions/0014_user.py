"""User: users 表（Step 21 登录注册）。

Revision ID: 0014_user
Revises: 0013_play
Create Date: 2026-08-21
"""
import sqlalchemy as sa

from alembic import op

revision = "0014_user"
down_revision = "0013_play"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")