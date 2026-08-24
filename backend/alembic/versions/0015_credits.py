"""充值点数：users.credit_balance + redeem_codes + credit_ledger + credit_prices。

Revision ID: 0015_credits
Revises: 0014_user
Create Date: 2026-08-22
"""
import sqlalchemy as sa

from alembic import op

revision = "0015_credits"
down_revision = "0014_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) users 加余额列
    op.add_column("users", sa.Column("credit_balance", sa.Float(), server_default="0", nullable=False))

    # 2) 兑换码表
    op.create_table(
        "redeem_codes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("yuan", sa.Float(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("note", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("redeemed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_redeem_codes_code", "redeem_codes", ["code"], unique=True)
    op.create_index("ix_redeem_codes_redeemed_by", "redeem_codes", ["redeemed_by"])

    # 3) 流水表
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_ledger_user_id", "credit_ledger", ["user_id"])

    # 4) 价格表
    op.create_table(
        "credit_prices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_price", sa.Float(), nullable=False),
        sa.Column("output_price", sa.Float(), nullable=False),
        sa.Column("markup", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_prices_model", "credit_prices", ["model"], unique=True)


def downgrade() -> None:
    op.drop_table("credit_prices")
    op.drop_table("credit_ledger")
    op.drop_table("redeem_codes")
    op.drop_column("users", "credit_balance")
