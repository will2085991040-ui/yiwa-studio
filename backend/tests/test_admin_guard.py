"""管理员门禁测试：mint 兑换码 / 改引擎单价必须是 admin；指定 admin 自动提升。"""
from app.core.config import settings
from app.services.auth import create_user, promote_admins, sign_token


def test_mint_forbidden_for_plain_user(client, session_factory):
    s = session_factory()
    try:
        u = create_user(s, username="alice", password="secret123")
    finally:
        s.close()
    tok = sign_token(u.id)
    r = client.post("/api/credits/mint", json={"yuan": 10}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


def test_mint_requires_login(client):
    r = client.post("/api/credits/mint", json={"yuan": 10})
    assert r.status_code == 401, r.text


def test_set_price_forbidden_for_plain_user(client, session_factory):
    s = session_factory()
    try:
        u = create_user(s, username="bob", password="secret123")
    finally:
        s.close()
    tok = sign_token(u.id)
    r = client.post("/api/credits/prices", json={"model": "deepseek-chat", "input_price": 0.3, "output_price": 1.2}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


def test_first_user_promoted_to_admin(session_factory):
    s = session_factory()
    try:
        u = create_user(s, username="firstkid", password="secret123")
        promote_admins(s)
        s.refresh(u)
        assert u.role == "admin"
    finally:
        s.close()


def test_named_admin_promoted_from_env(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "admin_usernames", "boss,ceo")
    s = session_factory()
    try:
        boss = create_user(s, username="boss", password="secret123")
        ceo = create_user(s, username="ceo", password="secret123")
        promo = create_user(s, username="promo", password="secret123")
        promote_admins(s)
        s.refresh(boss)
        s.refresh(ceo)
        s.refresh(promo)
        assert boss.role == "admin" and ceo.role == "admin"
        assert promo.role == "user"
    finally:
        s.close()