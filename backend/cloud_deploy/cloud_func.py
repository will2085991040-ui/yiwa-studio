"""CloudBase / 腾讯云 SCF 云函数 HTTP 入口：把现有 FastAPI 应用桥接到云函数 HTTP 触发器。

每次 HTTP 请求 -> main_handler()：将 event 翻译成 ASGI scope -> 喂给既有 FastAPI app ->
将响应还原为 SCF 约定 {"statusCode","headers","body"} 返回。

安全要点：
- 密钥只从环境变量读取（在 CloudBase 控制台配置，含混元 HUNYU / 腾讯云 Secret / 厂商 key），
  代码、EXE、Git 里永远不含明文密钥。
- 复用 backend/app 全部既有路由：auth / credits(兑换码·余额) / orders / account / legal；
  LLM 走 provider.py 的 openai_compat(可接混元 OpenAI 兼容端点)。本文件只做桥接，不复制业务。
"""
import asyncio
import base64
import json
import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.main import create_app

_APP: "FastAPI | None" = None


def _get_app() -> "FastAPI":
    global _APP
    if _APP is None:
        os.environ.setdefault("APP_ENV", "cloud")
        _APP = create_app()
        _APP.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    return _APP


async def _run_asgi(app: FastAPI, scope: dict, body: bytes) -> dict:
    """最小 ASGI 泵：收集 status / headers / body。"""
    out = {"status": 200, "headers": [], "body": b""}

    async def send_msg(msg: dict) -> None:
        if msg["type"] == "http.response.start":
            out["status"] = msg.get("status", 200)
            out["headers"] = [
                (k.decode() if isinstance(k, bytes) else k,
                 v.decode() if isinstance(v, bytes) else v)
                for k, v in msg.get("headers", [])
            ]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    sent = {"done": False}

    async def recv_msg() -> dict:
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    await app(scope, recv_msg, send_msg)
    return out


def router_handler(event: dict, context: dict) -> dict:
    """CloudBase HTTP 触发入口。event 形如：
    {"path": ..., "httpMethod": ..., "headers": {...}, "queryString": {...},
     "body": ..., "isBase64Encoded": false}
    """
    path = event.get("path") or "/"
    method = (event.get("httpMethod") or "GET").upper()
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items() if k and v}

    body = event.get("body") or ""
    if event.get("isBase64Encoded") and body:
        body = base64.b64decode(body).decode("utf-8", errors="replace")

    qs = event.get("queryString") or {}
    query = "&".join(f"{k}={v}" for k, v in qs.items()) if isinstance(qs, dict) else ""

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("utf-8", "ignore"),
        "query_string": query.encode("utf-8", "ignore"),
        "root_path": "",
        "headers": [(k.encode("latin-1", "ignore"), v.encode("latin-1", "ignore")) for k, v in headers.items()],
        "client": ("0.0.0.0", 0),
        "server": ("cloudbase-func", 443),
    }
    try:
        out = asyncio.run(_run_asgi(_get_app(), scope, body.encode("utf-8", "replace")))
    except Exception:  # noqa: BLE001 - 云函数尽力返回 500
        traceback.print_exc()
        return {
            "statusCode": 500,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": {"code": "internal", "message": "云函数异常"}}),
            "isBase64Encoded": False,
        }

    body_text = out["body"].decode("utf-8", errors="replace")
    header_map = {k.lower(): v for k, v in out["headers"]}
    if "content-type" not in header_map:
        header_map["content-type"] = "application/json" if body_text.startswith("{") else "text/plain;charset=utf-8"
    return {"statusCode": out["status"], "headers": header_map, "body": body_text, "isBase64Encoded": False}


# CloudBase(SCF)HTTP 触发器默认入口名；如需改名为其他，在控制台指向对应函数即可。
def main_handler(event: dict, context: dict) -> dict:
    return router_handler(event, context)
