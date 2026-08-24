"""测试：登录注册（Step 21）。用户名+密码+JWT，真实后端。"""


def _token(client, route, **body):
    r = client.post(route, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def test_register_and_me(client):
    r = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["username"] == "alice"
    token = body["token"]

    # /me 用 token 取回用户
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "alice"


def test_login_and_verify(client):
    client.post("/api/auth/register", json={"username": "bob", "password": "secret123"})
    # 正确密码
    r = client.post("/api/auth/login", json={"username": "bob", "password": "secret123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    # token 可用
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    # 错误密码 401
    r = client.post("/api/auth/login", json={"username": "bob", "password": "wrong!"})
    assert r.status_code == 401, r.text


def test_duplicate_username_409(client):
    client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    r = client.post("/api/auth/register", json={"username": "carol", "password": "other123"})
    assert r.status_code == 409, r.text


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401, r.text


def test_short_password_rejected(client):
    # pydantic 强校验（password min_length=6）→ 422
    r = client.post("/api/auth/register", json={"username": "dave", "password": "123"})
    assert r.status_code == 422, r.text