"""AUTH_REQUIRED 强制登录门禁测试：生产开启时项目接口无 token 401、带 token 通过；默认关闭时放行。"""
import pytest

from app.core.config import settings
from app.services.auth import create_user, sign_token


@pytest.fixture()
def auth_on():
    prev = settings.auth_required
    settings.auth_required = True
    try:
        yield
    finally:
        settings.auth_required = prev


def _make_user(session_factory, username="gate_user", password="secret123"):
    s = session_factory()
    try:
        u = create_user(s, username, password)
        return u
    finally:
        s.close()


def test_project_endpoint_requires_login_when_enabled(client, session_factory, auth_on):
    r = client.get("/api/agents")
    assert r.status_code == 401, r.text
    assert "登录" in r.json().get("error", {}).get("message", "") or "登录" in r.text


def test_project_endpoint_passes_with_token(client, session_factory, auth_on):
    u = _make_user(session_factory)
    tok = sign_token(u.id)
    r = client.get("/api/agents", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text


def test_register_login_still_public_when_auth_on(client, auth_on):
    r = client.post("/api/auth/register", json={"username": "pub", "password": "secret123"})
    assert r.status_code == 201, r.text
    body = r.json()
    r2 = client.get("/api/agents", headers={"Authorization": f"Bearer {body['token']}"})
    assert r2.status_code == 200, r2.text


def test_default_off_allows_anonymous(client, session_factory):
    # AUTH_REQUIRED 默认 false（开发/test）时，项目接口匿名可访问（保留既有离线用例）。
    assert settings.auth_required is False
    r = client.get("/api/agents")
    assert r.status_code == 200, r.text


def test_status_reports_auth_required(client, auth_on):
    # 公开元信息接口：强制登录模式下必须返回 auth_required=true（前端靠它跳转 /login）。
    r = client.get("/api/auth/status")
    assert r.status_code == 200, r.text
    assert r.json()["auth_required"] is True


def test_status_default_false(client):
    # 默认开发态：auth_required=false，前端不强制登录。
    r = client.get("/api/auth/status")
    assert r.status_code == 200, r.text
    assert r.json()["auth_required"] is False