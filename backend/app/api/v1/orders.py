"""点数购买订单 API：套餐下单(manual) + 管理员核销。支付渠道可插拔(本阶段 manual)。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import User
from app.services import orders as order_svc
from app.services.auth import require_admin, require_user_strict

router = APIRouter(prefix="/api/orders", tags=["orders"])


class CreateOrderInput(BaseModel):
    package: str = Field(min_length=3, max_length=32)
    payment_ref: str = Field(default="", max_length=200)
    provider: str = Field(default="manual", max_length=20)


class ReportInput(BaseModel):
    payment_ref: str = Field(default="", max_length=200)


class ConfirmInput(BaseModel):
    note: str = Field(default="", max_length=300)


@router.get("/packages")
def packages() -> dict:
    return {"items": [{"key": k, "yuan": y, "points": p} for k, (y, p) in order_svc.PACKAGES.items()]}


@router.post("")
def create_order(payload: CreateOrderInput, user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    order = order_svc.create_order(session, user, payload.package, payload.payment_ref, payload.provider)
    return order_svc.order_dict(order)


@router.get("/me")
def my_orders(user: User = Depends(require_user_strict), session: Session = Depends(get_session), limit: int = 50) -> dict:
    return {"items": [order_svc.order_dict(o) for o in order_svc.list_orders(session, user, limit)]}


@router.post("/{order_id}/report_paid")
def report_paid(order_id: str, payload: ReportInput, user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    order = order_svc.report_payment(session, user, order_id, payload.payment_ref)
    return order_svc.order_dict(order)


@router.post("/{order_id}/cancel")
def cancel(order_id: str, user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    order = order_svc.cancel_order(session, order_id)
    return order_svc.order_dict(order)


@router.get("/admin/pending")
def admin_pending(_admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> dict:
    return {"items": [order_svc.order_dict(o) for o in order_svc.list_pending(session)]}


@router.post("/{order_id}/confirm")
def confirm(order_id: str, payload: ConfirmInput, _admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> dict:
    order = order_svc.confirm_order(session, order_id, payload.note)
    return order_svc.order_dict(order)
