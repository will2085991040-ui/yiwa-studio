# YIWA Studio — AI 互动影游创作平台

> 面向『一个人也能做出互动影游』的可商用 AI 创作平台：可视化编辑器 + 多 Agent 剧情生成 + 关系图谱/分镜/小游戏，并内置引擎级 token 计费与充值点数体系。可打包为 Windows 单文件桌面应用，同一套后端也可 Web 部署。

![Python](https://img.shields.io/badge/Python-3.11-blue)
![Next.js](https://img.shields.io/badge/Next.js-14-black)
![FastAPI](https://img.shields.io/badge/FastAPI-SQLAlchemy%20%2B%20alembic-009688)
![License](https://img.shields.io/github/license/will2085991040-ui/yiwa-studio)
![CI](https://img.shields.io/github/actions/workflow/status/will2085991040-ui/yiwa-studio/ci.yml?branch=main)

## 一句话定位
> 不只会调 LLM API——能把 AI 应用从零搭到可商用：**Agent 编排 + 结构化输出 + 引擎级 token 计费 + 双端/桌面发布**，且在「不破坏既有功能」的约束下做增量工程。

## 文档导航
- [**ARCHITECTURE.md**](ARCHITECTURE.md) — 一页看懂架构与两大创新点(Agent 编排 + 引擎级计费)
- [docs/billing-architecture.md](docs/billing-architecture.md) — 点数计费体系与收费流图

## 项目亮点
- 一个仓库实现端到端 LLM 应用：Next.js 前端 + FastAPI 后端 + SQLite 存储 + PyInstaller 桌面打包。
- 多 Agent + 可视化：剧情/角色/分镜/关系图谱/小游戏的 AI 创作与可视化编辑。
- 引擎级点数计费：分模型、分输入/输出 token 单价，按 40% 毛利折算充值点数；兑换码充值 + 余额(可为负) + 流水可追溯。
- 存量系统增量改造：整套计费以『可插拔 hook + 请求级上下文』接入，对既有功能零破坏。
- 桌面版开箱即用：单文件 EXE + 内嵌 WebView2 窗口。

## 核心功能
- Agent 创作：生成可视化剧本 / 角色 / 分镜 / 故事线。
- 关系图谱、故事剧本、小游戏、视频面板等多模块。
- 登录鉴权(JWT/HMAC) + 多用户隔离。
- 点数账户：充值(兑换码) / 余额 / 流水 / 单价配置。
- 打包运行：双击即用，单实例端口优先、日志在 AppData 下。

## ✨ 创新与技术难点（面试可讲）
- 请求级上下文计费：Agent 内部调用没有用户身份，用 FastAPI 中间件解析鉴权 Bearer 得到 user id，写入 Async ContextVar（请求作用域），LLM 结算点据此同步扣费；业务代码零污染。
- 计费做成可插拔 hook 而非侵入式重构：LLM 基类拿到 usage 后挂 best-effort 扣费钩子，无上下文就不记、绝不 throw，存量接口零改动。
- 引擎级计价：分模型、分输入/输出 token 单价，扣点 = 成本 ÷ 0.6（×1.667，40% 毛利），/prices 后台可调。
- 余额可为负不硬卡：失败路径只记流水，不阻断既有工作流，兼顾体验与账目准确。
- 真实翻车修复：alembic history 与真实库不一致升级中断 → 以真实干净库对齐 head 重建；桌面端单实例端口优先 + 复用进程，消除重复启动红框/重复进程。
- 完整测试：80+ 后端测试（provider 契约 / 计费 / 鉴权 / 媒体 / 剧本链路）由 GitHub Actions 自动跑。

## 技术栈
- 前端：Next.js 14(静态导出)、React、Canvas、Tailwind
- 后端：FastAPI、SQLAlchemy、alembic、JWT 鉴权
- 数据库：SQLite(WAL)，存放于 %APPDATA%/YIWA
- LLM：异步接入层(OpenAI 兼容 API)，可接入 DeepSeek / MiniMax 等
- 桌面：PyWebView + WebView2 + PyInstaller 单文件 EXE

## 点数计费(核心特色)
- 扣费点数 = token 成本 ÷ 0.6(即 ×1.667，对应 40% 毛利)
- 单价按 模型 / 输入 / 输出 分别配置(元/百万 token)，后台可调
- 余额可为负数：不阻断既有流程，仅记流水
- 充值采用 兑换码 体系，全流程可追溯

## 启动(本地开发)
- cd backend：创建虚拟环境并 pip install -r requirements.txt
- alembic upgrade head 初始化/升级数据库
- uvicorn app.main:app --host 127.0.0.1 --port 8875 启动后端
- cd frontend && npm install && npm run build(生成静态导出 out)

## 打包为桌面应用
- cd backend && pyinstaller --clean --noconfirm desktop/yiwa.spec
- 产物 backend/dist/YIWA.exe，双击即可运行(内嵌 WebView2)

## 仓库结构
- backend/    FastAPI 后端 + alembic 迁移 + PyInstaller 配置
- frontend/   Next.js 前端(静态导出 out)
- desktop/    launcher 与打包配置
- docs/       架构与设计：architecture / billing-architecture（点数计费）
- .github/    CI 配置

## 环境与密钥
- 所有密钥仅放 .env / env.local，仓库已通过 .gitignore 排除，永不进入版本库。

## License
MIT

## 作者
王鹏

---
由本人独立开发与打包。若对你有帮助，欢迎 Star。