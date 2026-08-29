#!/usr/bin/env python
"""tokenhub/腾讯云网关 全链路连通测试(不含 key，只读环境变量/参数/.env)。

用法(任选其一):
  1) python -m scripts.test_connectivity --token sk-xxx --base https://tokenhub.tencentmaas.com/v1
  2) 环境变量: TOKENHUB_KEY / TOKENHUB_BASE_URL
  3) .env 里的 TOKENHUB_KEY / TOKENHUB_BASE_URL
依次测: 文本chat / 文生视频 / 首尾帧 / 任务轮询。只打印打码 key，绝不打印明文 key。
"""
import asyncio
import os
import pathlib
import sys

import httpx

DEFAULT_BASE = "https://tokenhub.tencentmaas.com/v1"


def _load_dotenv() -> None:
    p = pathlib.Path(".env")
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k, v = k.strip(), v.strip().strip(chr(34)).strip(chr(39))
        if k and k not in os.environ:
            os.environ[k] = v

def _mask_key(k: str) -> str:
    if not k:
        return "(空)"
    return k[:4] + "..." + (k[-4:] if len(k) > 8 else "")

def _auth(key: str) -> dict:
    return {"Authorization": "Bearer " + key, "Content-Type": "application/json"}

async def test_text(client, base, key):
    payload = {"model": "hy-role", "messages": [{"role": "user", "content": "只回复:ok"}], "stream": False}
    r = await client.post(base.rstrip("/") + "/chat/completions", json=payload, headers=_auth(key), timeout=60)
    print("[1/文本] POST /chat/completions ->", r.status_code)
    if r.status_code < 400:
        try:
            d = r.json()
            print("       回应:", (d.get("choices") or [{}])[0].get("message", {}).get("content", "")[:80])
        except Exception:
            print("       body:", r.text[:200])
    else:
        print("       error:", r.text[:200])

async def _video(client, base, key, mode):
    path = base.rstrip("/") + "/wand/minimax-video-v2/generation"
    content = [{"type": "text", "text": "清晨咖啡馆一杯咖啡冒着热气"}]
    if mode == "firstlast":
        content.append({"type": "image_url", "image_url": {"url": "https://example.com/start.jpg"}, "role": "first_frame"})
        content.append({"type": "image_url", "image_url": {"url": "https://example.com/end.jpg"}, "role": "last_frame"})
    payload = {"model": "minimax-video-h3", "content": content, "resolution": "768P", "duration": 4}
    r = await client.post(path, json=payload, headers=_auth(key), timeout=60)
    print("[", "2" if mode == "firstlast" else "3", "/视频]", mode, "->", r.status_code)
    if r.status_code >= 400:
        print("       error:", r.text[:200])
        return None
    d = r.json()
    task = d.get("task_id") or d.get("id") or (d.get("data") or {}).get("task_id") or (d.get("data") or {}).get("id")
    print("       task_id:", task or "(未找到, 顶层keys=" + str(list(d.keys())) + ")")
    return task

async def _poll(client, base, key, task_id):
    url = base.rstrip("/") + "/wand/minimax-video-v2/tasks/" + str(task_id)
    r = await client.get(url, headers={"Authorization": "Bearer " + key}, timeout=40)
    print("[轮询] GET", url, "->", r.status_code)
    if r.status_code < 400:
        print("       body:", r.text[:250])
    else:
        print("       error:", r.text[:200])

def _parse(argv):
    a = {}
    i = 0
    while i < len(argv):
        x = argv[i]
        if x in ("--token", "--key", "--base"):
            a[x.strip("-")] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif x in ("--help", "-h"):
            a["help"] = True
            i += 1
        else:
            i += 1
    return a

async def _main() -> int:
    a = _parse(sys.argv[1:])
    _load_dotenv()
    key = (a.get("token") or a.get("key") or os.environ.get("TOKENHUB_KEY") or os.environ.get("TOKENHUB_API_KEY") or "").strip()
    base = (a.get("base") or os.environ.get("TOKENHUB_BASE_URL") or DEFAULT_BASE).strip()
    if a.get("help"):
        print(__doc__)
        return 0
    if not key:
        print("未读到 key。请 --token sk-... 或设环境变量 TOKENHUB_KEY(或 .env 的 TOKENHUB_KEY)", file=sys.stderr)
        return 2
    print("key:", _mask_key(key), "| base:", base)
    async with httpx.AsyncClient() as client:
        await test_text(client, base, key)
        t1 = await _video(client, base, key, "text2video")
        t2 = await _video(client, base, key, "firstlast")
        for tid in (t1, t2):
            if tid:
                await _poll(client, base, key, tid)
    print("done。若全是非401并拿到 task_id，说明代码侧可正常对接网关。")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))