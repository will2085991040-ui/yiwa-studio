"""账户数据导出 / 注销（隐私合规：可携带权 + 被遗忘权）。注销为硬删除关联数据。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import CodeOrder, CreditLedger, RedeemCode, User
from app.services.auth import require_user_strict

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/export")
def export(user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    """导出当前用户全部个人数据（可携带 JSON）。"""
    ledger = (
        session.query(CreditLedger)
        .filter(CreditLedger.user_id == user.id)
        .order_by(CreditLedger.created_at.desc())
        .all()
    )
    orders = (
        session.query(CodeOrder)
        .filter(CodeOrder.user_id == user.id)
        .order_by(CodeOrder.created_at.desc())
        .all()
    )
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "role": user.role,
            "balance": user.credit_balance,
        },
        "credits": [row.as_dict() for row in ledger],
        "orders": [
            {
                "id": o.id,
                "status": o.status,
                "provider": o.provider,
                "amount_yuan": o.amount_yuan,
                "points": o.points,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "confirmed_at": o.confirmed_at.isoformat() if o.confirmed_at else None,
            }
            for o in orders
        ],
    }


@router.post("/delete", status_code=200)
def delete_account(user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    """注销账号：删除该用户点数流水、订单并解绑其兑换码，最后删除账号本身（hard delete）。"""
    session.query(CreditLedger).filter(CreditLedger.user_id == user.id).delete(synchronize_session=False)
    session.query(CodeOrder).filter(CodeOrder.user_id == user.id).delete(synchronize_session=False)
    session.query(RedeemCode).filter(RedeemCode.redeemed_by == user.id).update(
        {RedeemCode.redeemed_by: None}, synchronize_session=False
    )
    username = user.username
    session.delete(user)
    session.commit()
    return {"deleted": True, "username": username}
