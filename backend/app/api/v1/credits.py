"""充值点数 API（增量）：余额 / 兑换码 / 流水 / 引擎单价。

端点都走 require_user_strict（生产 EXE 强制登录）。纯增量，不与既有接口冲突。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import CreditPrice, User
from app.services.auth import require_user_strict
from app.services import credits as creds

router = APIRouter(prefix="/api/credits", tags=["credits"])


@router.get("/overview")
def overview(user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    """当前余额 + 计费口径（供前端展示）。"""
    return {
        "balance": creds.get_balance(user),
        "markup": creds.DEFAULT_MARKUP,
        "currency": "CNY",
        "unit": "point",
    }


@router.get("/ledger")
def ledger(user: User = Depends(require_user_strict), session: Session = Depends(get_session), limit: int = 50) -> dict:
    return {"items": creds.list_ledger(session, user, limit)}


class RedeemInput(BaseModel):
    code: str = Field(min_length=1, max_length=64)


@router.post("/redeem")
def redeem(payload: RedeemInput, user: User = Depends(require_user_strict), session: Session = Depends(get_session)) -> dict:
    points, balance = creds.redeem_code(session, user, payload.code)
    return {"redeemed_points": points, "balance": balance}


class MintInput(BaseModel):
    yuan: float = Field(gt=0)
    points: float | None = None
    note: str = Field(default="", max_length=200)
    code: str | None = Field(default=None, max_length=64)


@router.post("/mint", status_code=201)
def mint(payload: MintInput, session: Session = Depends(get_session)) -> dict:
    row = creds.mint_code(session, yuan=payload.yuan, points=payload.points, note=payload.note, code=payload.code)
    return {"code": row.code, "yuan": row.yuan, "points": row.points}


@router.get("/prices")
def prices(session: Session = Depends(get_session)) -> dict:
    rows = session.query(CreditPrice).order_by(CreditPrice.model.asc()).all()
    items = [
        {"model": r.model, "input_price": r.input_price, "output_price": r.output_price, "markup": r.markup}
        for r in rows
    ]
    return {"markup": creds.DEFAULT_MARKUP, "defaults": creds.DEFAULT_PRICES, "items": items}


class PriceInput(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    input_price: float = Field(ge=0)
    output_price: float = Field(ge=0)
    markup: float | None = Field(default=None, gt=0)


@router.post("/prices")
def set_prices(payload: PriceInput, session: Session = Depends(get_session)) -> dict:
    row = creds.set_price(session, payload.model, payload.input_price, payload.output_price, payload.markup)
    return {"model": row.model, "input_price": row.input_price, "output_price": row.output_price, "markup": row.markup}
