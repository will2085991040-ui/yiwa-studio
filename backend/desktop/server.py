"""桌面版 FastAPI（Step 21）：复用主 create_app() + 静态前端挂载 + 健康检查。

前端产物（web_root）与后端 /api 同源部署：前端相对 /api 请求直达后端，无需代理。
未提供 web_root 时使用内置启动页，确保 EXE 即使不打包前端也能启动并给出健康信息。
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

_SPLASH = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>YIWA · AI Interactive Content OS</title></head>
<body style="font-family:system-ui,sans-serif;background:
radial-gradient(800px 500px at 20% -10%, rgba(139,92,246,.25), transparent 60%),
radial-gradient(700px 500px at 110% 10%, rgba(34,211,238,.18), transparent 55%),#06070d;
color:#e5e7eb;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
  <div style="text-align:center;max-width:40rem">
    <h1 style="background:linear-gradient(90deg,#8b5cf6,#22d3ee,#f472b6);-webkit-background-clip:text;background-clip:text;color:transparent;font-size:2.6rem">YIWA ∞</h1>
    <p>AI 互动内容创作操作系统 · 桌面服务已启动</p>
    <p style="color:#94a3b8">访问 <code>/health</code> 查看健康状态，前端 API 挂载于 <code>/api/*</code>。</p>
    <p style="color:#64748b;font-size:0.85rem">
      打包前端静态产物后，将 <code>web_root</code> 指向该目录即可加载完整界面。
    </p>
  </div>
</body>
</html>"""


def build_desktop_app(web_root: str = "") -> FastAPI:
    from app.main import create_app

    app = create_app()
    web_dir = web_root if web_root and os.path.isdir(web_root) else ""

    @app.get("/health", include_in_schema=False)
    def _health() -> dict:
        return {"status": "ok", "app": "YIWA", "web_root": bool(web_dir)}

    if web_dir:
        base = os.path.realpath(web_dir)

        @app.get("/{full_path:path}", include_in_schema=False)
        def _static(full_path: str) -> FileResponse:
            """静态导出前端：无扩展名路由映射到同名 .html（/settings → settings.html）。"""
            safe = os.path.normpath(full_path).lstrip("\\/").replace("\\", "/")
            candidates = [os.path.join(base, "index.html")] if not safe else [
                os.path.join(base, safe),
                os.path.join(base, safe + ".html"),
                os.path.join(base, safe, "index.html"),
            ]
            for cand in candidates:
                real = os.path.realpath(cand)
                if real.startswith(base) and os.path.isfile(real):
                    return FileResponse(real)
            raise HTTPException(status_code=404)
    else:

        @app.get("/", include_in_schema=False)
        def _splash() -> HTMLResponse:
            return HTMLResponse(_SPLASH)

    return app