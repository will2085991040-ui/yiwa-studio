"""订单/支付(manual)流程测试：下单 -> 管理员核销 -> 用户余额到账；权限门禁。"""
from app.services.auth import create_user, sign_token


def _mk(session_factory, username):
    s = session_factory()
    try:
        return create_user(s, username=username, password="secret123")
    finally:
        s.close()


def _admin_tok(session_factory):
    s = session_factory()
    try:
        u = create_user(s, username="root", password="secret123")
        u.role = "admin"
        s.commit()
        return sign_token(u.id)
    finally:
        s.close()


def test_packages_public(client):
    r = client.get("/api/orders/packages")
    assert r.status_code == 200, r.text
    assert any(it["key"] == "pack_50" and it["points"] == 55 for it in r.json()["items"])


def test_create_order_and_fulfill(client, session_factory):
    u = _mk(session_factory, "buyer")
    utok = sign_token(u.id)
    r = client.post("/api/orders", json={"package": "pack_50"}, headers={"Authorization": f"Bearer {utok}"})
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    assert r.json()["status"] == "pending_payment"
    assert r.json()["points"] == 55

    # 非管理员不能核销
    r2 = client.post(f"/api/orders/{oid}/confirm", json={}, headers={"Authorization": f"Bearer {utok}"})
    assert r2.status_code == 403, r2.text

    # 管理员核销 -> 余额到账 55
    atok = _admin_tok(session_factory)
    r3 = client.post(f"/api/orders/{oid}/confirm", json={"note": "已到账"}, headers={"Authorization": f"Bearer {atok}"})
    assert r3.status_code == 200, r3.text
    assert r3.json()["status"] == "fulfilled"
    assert r3.json()["redeem_code"]  # 生成了可留痕的兑换码

    r4 = client.get("/api/credits/overview", headers={"Authorization": f"Bearer {utok}"})
    assert r4.json()["balance"] == 55.0

    # 幂等：重复核销不重复入账
    client.post(f"/api/orders/{oid}/confirm", json={}, headers={"Authorization": f"Bearer {atok}"})
    r5 = client.get("/api/credits/overview", headers={"Authorization": f"Bearer {utok}"})
    assert r5.json()["balance"] == 55.0


def test_order_requires_login(client):
    r = client.post("/api/orders", json={"package": "pack_10"})
    assert r.status_code == 401, r.text
