# YIWA Studio — AI 互动影游创作平台

> 面向『一个人也能做出可商用的互动影游』的 AI 创作平台：可视化编辑器 + 多 Agent 剧情生成 + 关系图谱 / 分镜 / 小游戏，内置引擎级 token 计费与充值点数体系。同一套前后端既能打包为 **Windows 单文件桌面应用**，也能作为 Web 部署。

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![FastAPI](https://img.shields.io/badge/FastAPI-SQLAlchemy%20%2B%20Alembic-009688)
![FFmpeg](https://img.shields.io/badge/剪辑引擎-FFmpeg-green)
![License](https://img.shields.io/github/license/will2085991040-ui/yiwa-studio)
![CI](https://img.shields.io/github/actions/workflow/status/will2085991040-ui/yiwa-studio/ci.yml?branch=main)

---

## 目录
- [功能总览](#功能总览)
- [分镜 → 逐个生视频 → 页面剪辑成片（核心视频链路）](#分镜视频链路)
- [技术栈](#技术栈)
- [亮点 / 创新点](#亮点--创新点)
- [点数计费（核心特色）](#点数计费核心特色)
- [本地开发启动](#本地开发启动)
- [打包桌面应用](#打包桌面应用)
- [仓库结构](#仓库结构)
- [开发者文档](#开发者文档)
- [环境与密钥](#环境与密钥)
- [License](#license)

---

## 一句话定位
不只会调 LLM API——能把一个 AI 应用**从零搭到可商用**：**Agent 编排 + 结构化输出 + 引擎级 token 计费 + 前端/后端/桌面三端交付**，并在「不破坏既有功能」的约束下做增量工程。

## 功能

**🎬 影游创作**
- 多 Agent 剧情编排：角色 / 剧情 / 分镜 / 关系图谱 / 小游戏，结构化 Artifact + 锁定后可修改。
- 可视化编辑：剧情画布、节点小画布、关系图谱、角色立绘、世界设定。
- 文生图 + 文生视频：风格化出图（二次元/真人写实/动态漫画/史诗电影…），真实视频渲染（阿里 DashScope / 秘塔 MiniMax / 火山 Seedance）。

**🎞️ 分镜视频链路（本仓库特色）**
- **整列拆镜** → 每个分镜镜头分别生成一段独立视频。
- **页面剪辑**：时间轴排序、转场（硬切 / 淡入淡出）、预览，一键 **导出完整成片**（本地 ffmpeg 离线合成）。
- 生成参数可控：**分辨率**（默认 768P，可选 1080P/2K/4K）、**时长（4–15s 可选）**、**首帧图 / 尾帧图**（用首尾帧控制视频的开始与结束画面）。

**💰 引擎级点数计费**
- 分模型、分输入/输出 token 单价，扣点 = 成本 ÷ 0.6（×1.667，40% 毛利）；兑换码充值 + 余额（可为负）+ 流水可追溯。

**🏙️ 发布**
- 单文件 Windows EXE + 内嵌 WebView2；同一后端也可 Web 部署；Docker Compose 一键起。

## 分镜视频链路

```
整列拆镜(Storyboard.shots)
   │  compose_shot_prompt 生成每镜头的独立提示词
   ▼
逐镜头生成(每镜头一个厂商 task, 独立排队/轮询/落库)
   │  + ref_image(首帧) / ref_image_last(尾帧) / resolution(768P…) / duration(4-15s)
   ▼
页面剪辑 UI (时间轴排序 ←→ / 转场选择 / 每镜预览)
   │
   ▼
导出成片(本地 ffmpeg imageio-ffmpeg concat + 可选淡入淡出)
   └─> 下载完整 MP4 / 离线可用
```

- 后端：`POST/GET /api/projects/{id}/storyboard/{node}/video/clips`（逐个生成 + 轮询），`POST …/clips/compose`（ffmpeg 合成）。
- 引擎：**开源 FFmpeg**（经 `imageio-ffmpeg` 自带的静态二进制，离线可用，已打成 data 一并随 EXE 发布）。
- 详见 [docs/film-pipeline.md](docs/film-pipeline.md)。

## 技术栈
- 前端：Next.js 14（静态导出 `out`）、React、Canvas、Tailwind CSS
- 后端：FastAPI、SQLAlchemy、Alembic、JWT/HMAC 鉴权
- 数据库：SQLite（WAL，位于 `%APPDATA%/YIWA/data`）
- LLM：异步兼容层（OpenAI 兼容 API，可接 DeepSeek / MiniMax 等）；未配置 key 自动回退 MockProvider，离线可跑
- 生成：文生图 SiliconFlow；文生视频 阿里 DashScope / 秘塔 MiniMax / 火山 Seedance
- 剪辑：FFmpeg（imageio-ffmpeg）
- 桌面：PyWebView + WebView2 + PyInstaller 单文件 EXE

## 亮点 / 创新点
- **请求级上下文计费**：Agent 内部调用无用户身份，用 FastAPI 中间件解析鉴权 Bearer 得 user id，写入 `Async ContextVar`（请求作用域），LLM 结算点据此同步扣费；业务零污染。
- **计费做成可插拔 hook**：LLM 基类拿到 usage 后挂 best-effort 扣费钩子，无上下文不记、绝不 throw，存量接口零改动。
- **引擎级计价**：分模型、分输入/输出单价，扣点 = 成本 / 0.6（40% 毛利），`/prices` 后台可调。
- **真实翻车修复**：alembic history 与真实库不一致 → 以真实干净库对齐 head 重建；桌面单实例端口优先 + 复用进程，消除重复启动。
- **真实视频逐镜头生成 + 页面剪辑成片**：分镜每个镜头独立真实渲染任务，拉起时间轴剪辑，ffmpeg 离线合成最终成片。
- 完整测试：80+ 后端测试（provider 契约 / 计费 / 鉴权 / 媒体 / 剧本链路），GitHub Actions 自动跑。

## 点数计费（核心特色）
- 扣费点数 = token 成本 / 0.6（即 ×1.667，对应 40% 毛利）。
- 单价按 模型/输入/输出 分别配置（元/百万 token），后台可调。
- 余额可为负数：失败路径只记流水，不阻断流程，仅记流水。
- 充值为 兑换码 体系，全流程可追溯。

## 快速开始启动（本地开发）
```bash
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head            # 初始化/升级数据库
uvicorn app.main:app --host 127.0.0.1 --port 8875

cd frontend
npm install
npm run build                   # 静态导出 out/
```

## 打包桌面应用
```bash
cd backend
pyinstaller --clean --noconfirm desktop/yiwa.spec
# 产物 backend/dist/YIWA.exe，双击运行（内嵌 WebView2；含 ffmpeg 二进制，离线可合成成片）
```

## 仓库结构
```
├─ backend/        FastAPI 后端 + Alembic 迁移 + 媒体生成(图/视频/ffmpeg 合成)
│  ├─ app/
│  │  ├─ media/    图片/视频生成 + compose.py(ffmpeg 成片合成)
│  │  ├─ api/v1/    REST 接口（含 storyboard/video/clips/compose）
│  │  └─ agents/    多 Agent 编排（Director/World/Character…）
│  └─ desktop/      launcher + PyInstaller yiwa.spec
├─ frontend/        Next.js 前端（静态导出 out/），含 storyboard 剪辑页、小画布
├─ docs/            架构 / 计费 / 视频链路
├─ .github/workflows/  CI（ruff + pytest + frontend build）
├─ ARCHITECTURE.md  一页看懂架构
└─ docker-compose.yml
```

## 开发者文档
- [ARCHITECTURE.md](ARCHITECTURE.md) — 一页看懂架构与创新点
- [docs/architecture.md](docs/architecture.md) — 组件级架构 + Agent 体系
- [docs/billing-architecture.md](docs/billing-architecture.md) — 点数计费体系与收费流图
- [docs/film-pipeline.md](docs/film-pipeline.md) — 分镜逐镜头生成 → 页面剪辑 → ffmpeg 成片链路
- [docs/career-capability-matrix.md](docs/career-capability-matrix.md) — 能力矩阵（实现/规划）
- [.github/workflows/ci.yml](.github/workflows/ci.yml) — CI：static check + 测试 + 前端构建

## 环境与密钥
- 所有密钥仅放 `.env` / `.env.local`（或 `%APPDATA%/YIWA/data/config.json`），仓库已通过 `.gitignore` 排除，**任何真实 Key 永不入版本库**。
- 未配置密钥时自动回退 Mock，无需联网即可 demo。

## 许可
[MIT](LICENSE)

## 作者
王鹏

---
由本人原创开发与打包。若对你有帮助，欢迎 Star ⭐