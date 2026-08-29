"""本地冒烟：用假的 CloudBase event 打通云函数 ASGI 桥(不连真 MySQL/真 Key)。

用法:在 backend/ 下
    python -m cloud_deploy._smoke
会:
  1. 用临时 SQLite 作为 DB(避免依赖云端 MySQL)
  2. 通过 cloud_func.main_handler 依次模拟 HTTP 事件:
     GET /privacy, GET /api/auth/status,
     POST /api/auth/register -> 得到 token,
     POST /api/orders (create), GET /api/orders/packages
  断言每个返回码与 JSON 结构,最后打印 PASS/FAIL。
"""
import json
import os
import sys

_TMP_DB = os.path.join(os.path.dirname(__file__), "_smoke.db")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)  # 每次从干净库启动,保证可重复运行
# 必须在 backend import app 之前把环境变量钉死(纯增量,不影响既有 dev/生产分支)
os.environ["DATABASE_URL"] = "sqlite:///" + _TMP_DB.replace("\\", "/")
os.environ["APP_ENV"] = "smoke"
os.environ["AUTH_REQUIRED"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cloud_deploy.cloud_func import main_handler  # noqa: E402


def send(method: str, path: str, body: dict | None = None, headers: dict | None = None) -> dict:
    evt = {
        "path": path,
        "httpMethod": method,
        "headers": headers or {},
        "queryString": {},
        "body": json.dumps(body) if body is not None else "",
        "isBase64Encoded": False,
    }
    return main_handler(evt, {})


def main() -> None:
    r = send("GET", "/privacy")
    assert r["statusCode"] == 199 or r["statusCode"] == 200, r
    print("[1] GET /privacy ->", r["statusCode"], r["body"][:60])

    r = send("GET", "/api/auth/status")
    assert r["statusCode"] == 200, r
    print("[2] GET /api/auth/status ->", r["statusCode"], r["body"][:60])

    # 注册一个用户,拿到 token
    username = "smoke_user_1"
    reg = send("POST", "/api/auth/register", {"username": username, "password": "pass123456"})
    assert reg["statusCode"] in (200, 201), reg
    token = json.loads(reg["body"]).get("token")
    assert token, reg
    print("[3] POST /api/auth/register ->", reg["statusCode"], "token ok")

    auth = {"Authorization": "Bearer " + token}
    r = send("GET", "/api/credits/overview", headers=auth)
    assert r["statusCode"] == 200, r
    print("[4] GET /api/credits/overview ->", r["statusCode"], r["body"][:80])

    r = send("POST", "/api/orders", {"package": "pack_10"}, headers=auth)
    assert r["statusCode"] == 200, r
    oid = json.loads(r["body"]).get("id")
    assert oid, r
    print("[5] POST /api/orders(pack_10) ->", r["statusCode"], "order=", oid)

    r = send("GET", "/api/orders/me", headers=auth)
    assert r["statusCode"] == 200, r
    print("[6] GET /api/orders/me ->", r["statusCode"], "orders listed")

    print("\n### SMOKE PASS: CloudBase ASGI bridge works (5 flows). ###")


if __name__ == "__main__":
    main()
