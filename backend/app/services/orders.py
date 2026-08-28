"""点数购买订单 + 可插拔支付渠道(本阶段 manual：人工到账后管理员核销)。

流程：用户创建订单(选套餐) -> 管理员确认收款 confirm -> 系统 mint 兑换码并直接入账用户余额，
     便于审计与后续切真支付通道(wechat/alipay/stripe)而不改业务代码。
"""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models import CodeOrder, User
from app.services import credits

# 可售套餐：{key: (应付元, 点数)}。1 点 = 1 元；批量略增配(如 50 元送 55 点)。
PACKAGES: dict[str, tuple[float, float]] = {
    "pack_10": (10.0, 10.0),
    "pack_30": (30.0, 32.0),
    "pack_50": (50.0, 55.0),
    "pack_100": (100.0, 115.0),
}


def package_points(package_key: str) -> tuple[float, float]:
    """返回 (应付元, 点数)；非法套餐抛 400。"""
    if package_key not in PACKAGES:
        raise AppError("未知套餐", code="bad_package", status=400)
    return PACKAGES[package_key]


def create_order(session: Session, user: User, package_key: str, payment_ref: str = "", provider: str = "manual") -> CodeOrder:
    yuan, points = package_points(package_key)
    order = CodeOrder(user_id=user.id, provider=provider, status="pending_payment",
                      amount_yuan=yuan, points=points, payment_ref=payment_ref[:200])
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def report_payment(session: Session, user: User, order_id: str, payment_ref: str = "") -> CodeOrder:
    """用户标记已转账(manual)；仅本人、且处于 pending_payment 的订单可更新备注。"""
    order = _get_order(session, order_id, user)
    if order.status != "pending_payment":
        raise AppError("订单状态已变更，无法修改", code="order_status", status=409)
    if payment_ref:
        order.payment_ref = payment_ref[:200]
    session.commit()
    session.refresh(order)
    return order


def _now() -> datetime:
    return datetime.now(UTC)


def confirm_order(session: Session, order_id: str, note: str = "") -> CodeOrder:
    """管理员确认到账并核销：mint 兑换码 -> 直接入账用户余额 -> 置为 fulfilled(幂等)。"""
    order = session.get(CodeOrder, order_id)
    if order is None:
        raise NotFoundError("订单不存在")
    if order.status in ("fulfilled", "paid"):
        return order  # 幂等：重复 confirm 不重复入账
    user = session.get(User, order.user_id)
    if user is None:
        raise AppError("订单用户不存在", code="no_user", status=409)
    code = credits.mint_code(session, yuan=order.amount_yuan, points=order.points, note="订单 " + order.id)
    credits.redeem_code(session, user, code.code)  # 直接把点数入账，用户无需再手动兑换
    order.status = "fulfilled"
    order.paid_at = _now()
    order.fulfilled_at = _now()
    order.redeem_code = code.code
    if note:
        order.note = (order.note + " | " + note[:200]) if order.note else note[:300]
    session.commit()
    session.refresh(order)
    return order


def cancel_order(session: Session, order_id: str) -> CodeOrder:
    """用户或管理员取消未支付的订单。"""
    order = session.get(CodeOrder, order_id)
    if order is None:
        raise NotFoundError("订单不存在")
    if order.status != "pending_payment":
        raise AppError("仅待支付订单可取消", code="order_status", status=409)
    order.status = "cancelled"
    session.commit()
    session.refresh(order)
    return order


def list_orders(session: Session, user: User, limit: int = 50) -> list[CodeOrder]:
    return (session.query(CodeOrder).filter(CodeOrder.user_id == user.id)
            .order_by(CodeOrder.created_at.desc()).limit(max(1, min(limit, 200))).all())


def list_pending(session: Session) -> list[CodeOrder]:
    return (session.query(CodeOrder).filter(CodeOrder.status == "pending_payment")
            .order_by(CodeOrder.created_at.asc()).all())


def _get_order(session: Session, order_id: str, user: User) -> CodeOrder:
    order = session.get(CodeOrder, order_id)
    if order is None or order.user_id != user.id:
        raise NotFoundError("订单不存在")
    return order


def order_dict(order: CodeOrder) -> dict:
    return {
        "id": order.id,
        "provider": order.provider,
        "status": order.status,
        "amount_yuan": order.amount_yuan,
        "points": order.points,
        "payment_ref": order.payment_ref,
        "note": order.note,
        "redeem_code": order.redeem_code,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "fulfilled_at": order.fulfilled_at.isoformat() if order.fulfilled_at else None,
    }
