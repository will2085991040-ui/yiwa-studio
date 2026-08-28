"""账户导出/注销 + 隐私条款公共端点测试。"""
from app.services.auth import create_user, sign_token


def _mk(session_factory, name):
    s = session_factory()
    try:
        return create_user(s, username=name, password="secret123")
    finally:
        s.close()


def test_privacy_and_terms_public(client):
    r = client.get("/privacy")
    assert r.status_code == 200 and r.json()["title"].startswith("隐私政策")
    r2 = client.get("/terms")
    assert r2.status_code == 200 and r2.json()["title"].startswith("服务条款")


def test_export_requires_login(client):
    r = client.get("/api/account/export")
    assert r.status_code == 401, r.text


def test_export_returns_user_balance(client, session_factory):
    u = _mk(session_factory, "exporter")
    tok = sign_token(u.id)
    r = client.get("/api/account/export", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["username"] == "exporter"
    assert isinstance(body["credits"], list)
    assert isinstance(body["orders"], list)


def test_delete_removes_account(client, session_factory):
    u = _mk(session_factory, "goneuser")
    tok = sign_token(u.id)
    r = client.post("/api/account/delete", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    # 账号已删 -> 该 token 的后续 /me 应为 401
    r2 = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 401, r2.text
