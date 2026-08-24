"""充值点数：点数账户（余额）、兑换码充值、消费流水。

设计与既有功能正交，纯增量（不改动任何现有字段/接口）：
- 1 点 = 1 元人民币（面向用户的计费面值）。
- 充值：通过兑换码（RedeemCode），点数 = 兑换码面值（yuan）。
- 扣费：每次 LLM 用量，点数 = 引擎成本(RMB) / 0.6（即 ×1.667，保证 40% 毛利）。
- 余额允许为负（不阻塞已有工作流）。首次换码结束：通过 /api/v1/credits。
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class RedeemCode(Base):
    """兑换码：运营线下生成并给用户，用户在前端兑换充值点数。"""

    __tablename__ = "redeem_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    yuan: Mapped[float] = mapped_column(Float, nullable=False)
    points: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    redeemed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class CreditLedger(Base):
    """点数流水：每条入账/扣费记录。正向=入账，负向=扣费。"""

    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    delta: Mapped[float] = mapped_column(Float, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="consume", nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "delta": self.delta,
            "kind": self.kind,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CreditPrice(Base):
    """引擎 token 单价表（人民币 / 1M tokens）。后台可改。key=引擎名。"""

    __tablename__ = "credit_prices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    model: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    input_price: Mapped[float] = mapped_column(Float, nullable=False)
    output_price: Mapped[float] = mapped_column(Float, nullable=False)
    markup: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
