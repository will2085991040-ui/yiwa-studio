"""充值点数服务：余额 / 兑换码充值 / 消费扣费 / 引擎单价。

纯增量模块，不改动既有 agent/项目逻辑。
- 1 点 = 1 元人民币（面向用户）。
- 兑换码：运营 mint() 生成，用户 redeem() 兑换入账。
- 扣费：points = 引擎成本(RMB) / markup；markup 默认 0.6（等价 ×1.667，含 40% 毛利）。
- 余额允许为负（不阻塞既有工作流）。
"""
import secrets
import string
from datetime import UTC, datetime

from sqlalchemy.orm import Session
import contextvars
import logging
from typing import Optional

from app.db.base import SessionLocal

_log = logging.getLogger("credits")

# 若某次请求已鉴权出当前用户，Provider 结算时据此记一笔点数消费（最优，不阻塞、不影响现有流程）。
_credit_uid: contextvars.ContextVar[str] = contextvars.ContextVar("credit_uid", default="")


def bind_user_context(user_id: str) -> "contextvars.Token":
    """在请求作用域设置当前消费用户；返回 token 供 finally 恢复。"""
    return _credit_uid.set(user_id)


def reset_user_context(token) -> None:
    _credit_uid.reset(token)


def charge_from_context(model: str, provider: str, input_tokens: int, output_tokens: int) -> None:
    """若请求上下文绑定了用户，则为该用户记一笔点数消费（best-effort，不抛错）。"""
    uid = _credit_uid.get()
    if not uid:
        return
    try:
        s = SessionLocal()
        try:
            u = s.get(User, uid)
            if u is not None:
                charge_for_usage(s, u, model=model, provider=provider or "", input_tokens=input_tokens, output_tokens=output_tokens)
        finally:
            s.close()
    except Exception as exc:  # noqa: BLE001 - 扣费失败不影响主流程
        _logger.warning("charge_from_context failed: %s", exc)


from app.core.errors import AppError
from app.models import CreditLedger, CreditPrice, RedeemCode, User


# 默认单价（人民币 / 1M tokens）：配表缺失时兜底。
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "deepseek-v4": (4.0, 16.0),
    "deepseek-chat": (4.0, 16.0),
    "minimax-h3": (2.0, 8.0),
    "glm-4-flash": (0.0, 0.0),
}
DEFAULT_MARKUP: float = 0.6


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _gen_code(n: int = 16) -> str:
    """生成易输的兑换码：大写字母+数字，去易混淆字符。"""
    alphabet = string.ascii_uppercase + string.digits
    alphabet = alphabet.replace("O", "").replace("I", "").replace("0", "").replace("1", "")
    return "".join(secrets.choice(alphabet) for _ in range(n))


def _points_of(cost_rmb: float, markup: float) -> float:
    """成本人民币 -> 扣费点数：cost / markup（markup=0.6 即 x1.667，含 40% 毛利）。"""
    if markup <= 0:
        markup = DEFAULT_MARKUP
    return round(cost_rmb / markup, 6)


def get_price_tuple(session: Session, model: str) -> tuple[float, float, float]:
    """返回 (input_price, output_price, markup)（元/百万 token）。未配置用默认。"""
    row = session.query(CreditPrice).filter(CreditPrice.model == model).first()
    if row is not None:
        return (row.input_price, row.output_price, row.markup)
    inp, outp = DEFAULT_PRICES.get(model, (0.0, 0.0))
    return (inp, outp, DEFAULT_MARKUP)


def set_price(session: Session, model: str, input_price: float, output_price: float, markup: float | None = None) -> CreditPrice:
    """新增/更新某引擎单价（后台管理用）。"""
    row = session.query(CreditPrice).filter(CreditPrice.model == model).first()
    if row is None:
        row = CreditPrice(model=model, input_price=input_price, output_price=output_price, markup=markup or DEFAULT_MARKUP)
        session.add(row)
    else:
        row.input_price = input_price
        row.output_price = output_price
        if markup is not None:
            row.markup = markup
    session.commit()
    session.refresh(row)
    return row


def get_balance(user: User) -> float:
    return round(float(user.credit_balance or 0.0), 6)


def mint_code(session: Session, *, yuan: float, points: float | None = None, note: str = "", code: str | None = None) -> RedeemCode:
    """运营生成兑换码。点数默认 = 面值（1元=1点）。"""
    if yuan <= 0:
        raise AppError("面值需大于 0", code="invalid_yuan", status=400)
    final_points = round(points if points is not None else yuan, 6)
    final_code = (code or _gen_code()).strip().upper()
    if session.query(RedeemCode).filter(RedeemCode.code == final_code).first():
        raise AppError("兑换码已存在", code="code_exists", status=409)
    row = RedeemCode(code=final_code, yuan=round(yuan, 6), points=final_points, note=note or "", is_active=True)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def redeem_code(session: Session, user: User, code: str) -> tuple[float, float]:
    """兑换码兑换：入账点数，返回 (入账点数, 新余额)。"""
    final = code.strip().upper()
    row = session.query(RedeemCode).filter(RedeemCode.code == final).first()
    if row is None:
        raise AppError("兑换码不存在", code="code_not_found", status=404)
    if not row.is_active:
        raise AppError("兑换码已失效", code="code_inactive", status=400)
    if row.redeemed_by is not None:
        raise AppError("兑换码已被使用", code="code_used", status=400)
    row.redeemed_by = user.id
    row.redeemed_at = _now_utc()
    row.is_active = False
    user.credit_balance = (user.credit_balance or 0.0) + row.points
    session.add(CreditLedger(user_id=user.id, delta=row.points, kind="redeem", model="", provider="",
                             input_tokens=0, output_tokens=0, note=f"兑换码 {row.code} 充值 {row.yuan} 元"))
    session.commit()
    return (row.points, get_balance(user))


def charge_for_usage(session: Session, user: User, *, model, provider='', input_tokens: int = 0, output_tokens: int = 0, note: str = "") -> float:
    """按一次 LLM 用量扣点。余额可为负。返回扣点数。"""
    in_p, p, markup = get_price_tuple(session, model)
    cost_rmb = (input_tokens * in_p + output_tokens * p) / 1_000_000.0
    points = _points_of(cost_rmb, markup)
    if points == 0:
        return 0.0
    user.credit_balance = (user.credit_balance or 0.0) - points
    session.add(CreditLedger(user_id=user.id, delta=-points, kind="consume", model=model, provider=provider,
                             input_tokens=int(input_tokens), output_tokens=int(output_tokens),
                             note=note or f"{model} 用量扣点"))
    session.commit()
    return round(points, 6)


def list_ledger(session: Session, user: User, limit: int = 50) -> list[dict]:
    rows = (session.query(CreditLedger).filter(CreditLedger.user_id == user.id)
.order_by(CreditLedger.created_at.desc()).limit(max(1, min(limit, 200))).all())
    return [r.as_dict() for r in rows]