"""登录注册 API（Step 21）：/register /login /me，用户名+密码+JWT。

真实后端、自包含（无第三方认证依赖）。注册/登录均返回 token，
携带后在需要鉴权的接口经 `require_user` 解析当前用户。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.db.base import get_session
from app.models import User
from app.services.auth import create_user, require_user_strict, sign_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", include_in_schema=True)
def auth_status() -> dict:
    """公开元信息：当前是否要求登录（供前端决定是否跳转 /login）。"""
    return {"auth_required": bool(settings.auth_required)}


class RegisterInput(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class LoginInput(BaseModel):
    username: str
    password: str


class AuthOut(BaseModel):
    token: str
    user: dict


def _public(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/register", response_model=AuthOut, status_code=201)
def register(payload: RegisterInput, session: Session = Depends(get_session)) -> dict:
    user = create_user(session, payload.username, payload.password)
    return {"token": sign_token(user.id), "user": _public(user)}


@router.post("/login", response_model=AuthOut)
def login(payload: LoginInput, session: Session = Depends(get_session)) -> dict:
    user = (
        session.query(User)
        .filter(User.username == payload.username.strip())
        .first()
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError("用户名或密码错误", code="bad_credentials", status=401)
    return {"token": sign_token(user.id), "user": _public(user)}


@router.get("/me", response_model=dict)
def me(user: User = Depends(require_user_strict)) -> dict:
    return {"user": _public(user)}