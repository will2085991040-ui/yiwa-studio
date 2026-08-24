"""Login/register 认证服务（Step 21）。

自包含实现，仅用标准库，避免第三方依赖：
- 密码哈希：PBKDF2-HMAC-SHA256（hashlib.pbkdf2_hmac）→ 格式 `pbkdf2_sha256${iterations}${salt}${hash}`
- Token：HMAC-SHA256 签名的 compact token，结构与 JWT 兼容（header.payload.signature，
  base64url），payload 含 sub(user id)/username/iat/exp。
- 签发密钥派生自 settings.auth_secret，空则退化为从主机 + 进程随机盐派生的稳定值。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, UnauthorizedError
from app.db.base import get_session
from app.models import User

_PBKDF2_ITER = 210_000


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _signing_key() -> bytes:
    """返回稳定签名密钥：优先 settings.auth_secret，否则从主机名 + 进程标识派生。"""
    raw = (settings.auth_secret or "").strip()
    if raw:
        return raw.encode("utf-8")
    material = f"{os.uname().nodename if hasattr(os, 'uname') else 'yiwa'}:{uuid.getnode()}".encode()
    return hashlib.sha256(material).digest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iter_s, salt_b64, hash_b64 = stored.split("$")
        salt = _b64url_decode(salt_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iter_s))
        return hmac.compare_digest(_b64url(digest), hash_b64)
    except Exception:
        return False


def sign_token(user_id: str, ttl_seconds: int = 60 * 60 * 24 * 30) -> str:
    header_b64 = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + ttl_seconds}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_signing_key(), f"{header_b64}.{body}".encode(), hashlib.sha256).digest()
    return f"{header_b64}.{body}.{_b64url(sig)}"


def verify_token(token: str) -> str | None:
    """校验 Bearer token，成功返回 user_id，失败返回 None。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body, sig_b64 = parts
        expected = hmac.new(_signing_key(), f"{header_b64}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), sig_b64):
            return None
        payload = json.loads(_b64url_decode(body))
        if not isinstance(payload, dict) or payload.get("exp", 0) < int(time.time()):
            return None
        return str(payload.get("sub") or "")
    except Exception:
        return None


# ---- FastAPI 依赖 -----------------------------------------------------------
def require_user(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User | None:
    """从 `Authorization: Bearer <token>` 解析当前用户；AUTH_REQUIRED=false（开发/test）时放行。

    生产（desktop launcher 注入 AUTH_REQUIRED=true）强制所有项目接口登录；
    开发/test 默认关闭，保留既有离线用例。关闭时不抛错、直接返回 None（None 代表匿名放行）。
    """
    if not settings.auth_required:
        return None
    user_id = None
    if authorization and authorization.lower().startswith("bearer "):
        user_id = verify_token(authorization[7:].strip())
    if not user_id:
        raise UnauthorizedError("请先登录")
    user = session.get(User, user_id)
    if user is None:
        raise UnauthorizedError("账号不存在或已失效")
    return user


def require_user_strict(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> User:
    """始终强制登录（不受 AUTH_REQUIRED 控制）：用于 /me 等身份自证接口，无 token 一律 401。"""
    user_id = None
    if authorization and authorization.lower().startswith("bearer "):
        user_id = verify_token(authorization[7:].strip())
    if not user_id:
        raise UnauthorizedError("请先登录")
    user = session.get(User, user_id)
    if user is None:
        raise UnauthorizedError("账号不存在或已失效")
    return user


def create_user(session: Session, username: str, password: str) -> User:
    name = username.strip()
    if len(name) < 2 or len(name) > 32:
        raise AppError("用户名需 2–32 个字符", code="invalid_username", status=400)
    if len(password) < 6:
        raise AppError("密码至少 6 位", code="invalid_password", status=400)
    exists = session.query(User).filter(User.username == name).first()
    if exists:
        raise AppError("用户名已被占用", code="username_taken", status=409)
    user = User(username=name, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return user