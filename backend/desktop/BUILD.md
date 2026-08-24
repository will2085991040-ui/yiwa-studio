# YIWA 桌面版打包（Step 21）

## 架构

桌面 EXE = 本地后端（FastAPI + SQLite）+ 前端静态站点 + Alembic 迁移 + 配置/数据目录。

启动流程（统一）：双击 `YIWA.exe` →
1. 初始化用户数据目录 `%APPDATA%\YIWA\data`（`config.json`、`yiwa.db`、`projects\`）
2. 初始化/升级数据库：`alembic upgrade head`
3. 启动 Backend（Uvicorn，默认 `http://127.0.0.1:8765`）
4. 同源托管前端静态站点（打包在 EXE 内，`/api/*` 直达后端，无需代理）
5. 自动打开浏览器进入 Web UI

## 一键打包（Windows）

```powershell
cd backend
powershell -ExecutionPolicy Bypass -File desktop\build_exe.ps1
# 产物：backend\dist\YIWA.exe
```

脚本会自动：安装 PyInstaller → `npm run build` 生成 `frontend\out`（静态导出）→ 跑后端测试 → PyInstaller 打单文件 EXE。

## 开发态预览（不打包）

```powershell
cd backend
.\.venv\Scripts\python.exe -m desktop --data-dir .\data --port 8765
# 浏览器打开 http://127.0.0.1:8765/
```

## 冒烟测试

```powershell
cd backend
.\.venv\Scripts\python.exe desktop\smoke_test.py dist\YIWA.exe   # 对 EXE
.\.venv\Scripts\python.exe desktop\smoke_test.py --dev           # 对开发态
```

覆盖：EXE 启动 / `/health` / 数据目录 / config.json / SQLite / migration / 前端页面 /
创建 Project / 一次 AI 创作 / Play Runtime / 重启数据持久化。

## 前端（产品化说明）

前端已改为 **纯静态导出**（`next.config.mjs` 设 `output: "export"`）：
- `/` 首页、`/agent?project=<id>` 工作台均为静态页，`npm run build` 产出 `frontend\out`；
- 移除了仅用于 `next dev`/`next start` 的 BFF 代理（`app/api/**/route.ts`）——
  桌面态后端与前端同源，前端相对 `/api` 请求直达 FastAPI；
- `frontend\out` 已作为 datas 打入 EXE，`web_root` 无需再手动配置。

## 切换 LLM

默认 `llm_provider=mock`（完全离线）。接入真实模型：编辑
`%APPDATA%\YIWA\data\config.json`：

```json
{
  "llm_provider": "openai_compat",
  "llm_base_url": "https://api.deepseek.com",
  "llm_api_key": "sk-...",
  "llm_model": "deepseek-chat"
}
```

注意：密钥仅存于本地 `config.json`，不入库、不硬编码、不入版本控制。

## 停止

控制台 Ctrl+C（或关闭控制台窗口）即优雅退出；数据持久在 `%APPDATA%\YIWA\data\yiwa.db`。