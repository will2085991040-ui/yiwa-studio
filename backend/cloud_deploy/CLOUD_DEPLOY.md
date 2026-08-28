# 部署到 CloudBase（腾讯云云开发 / SCF 云函数）

> 目标：把**数据库、兑换码、订单、鉴权、计费、混元 LLM 生成**全部放到 CloudBase 云端，
> 客户端(EXE/网页)只保留调用超薄壳，**客户端内不含数据库、不含任何厂商 API Key** —— 从源头防破解。

本目录新增 `backend/cloud_deploy/`，**不改动**现有本地分支(`dev` / `backend/app`)里的任何业务代码；
云端直接复用 `backend/app` 全部路由(credits/orders/auth/account/legal)与 `provider.py`(openai_compat → 混元)。

---

## 一、架构（防破解核心）

```
浏览器/桌面EXE(仅UI+用户token)
        │  HTTPS
        ▼
CloudBase HTTP 云函数(cloud_func.py)
   ├─ FastAPI 复用 backend/app（auth/credits/orders/account）
   ├─ 混元 LLM：openai_compat 走 LLM_BASE_URL + LLM_API_KEY(环境变量)
   └─ CloudBase MySQL（users / redeem_codes / code_orders / credit_ledger …）
```

**任何“破解”EXE 的人最多只能看到自己的会话 token，拿不到数据库、拿不到厂商 Key。**

---

## 二、需要你准备的（不给我账号，你自己在控制台点）

1. **开通 CloudBase 个人版**（你已有），新建一个环境。
2. **云数据库 MySQL**：创建数据库，记下连接串 `host:port/user/pass/db`。
3. **云函数**：运行时 **Python 3.11**，创建函数，代码指向本目录(见下)。

---

## 三、部署步骤

### 1) 把云端代码上传为云函数

把本仓库上传到 CloudBase 后，函数入口选：
```
函数入口 handler: cloud_deploy.cloud_func.main_handler
```
把 `backend/` + `backend/cloud_deploy/` 打进部署包（CloudBase 控制台「函数代码」打包上传即可）。

依赖用 `requirements-cloud.txt`（已把 psycopg2 换成 pymysql，去掉 dev 依赖）。

### 2) 配置环境变量（重点：密钥只放这）
在「云函数 → 配置 → 环境变量」填：
| 变量 | 值 |
|---|---|
| `DATABASE_URL` | `mysql+pymysql://用户:密码@主机:端口/库名?charset=utf8mb4` |
| `APP_ENV` | `cloud` |
| `AUTH_REQUIRED` | `true` |
| `AUTH_SECRET` | 随机长串 |
| `ADMIN_USERNAME` | 管理员用户名(逗号分隔) |
| `LLM_PROVIDER` | `openai_compat` |
| `LLM_BASE_URL` | `https://api.hunyuan.cloud.tencent.com/v1`(以官方为准) |
| `LLM_API_KEY` | 你的混元 key（真 key**绝不留**在代码/Git/EXE） |
| `LLM_MODEL` | 你的混元模型名 |
| `VIDEO_PROVIDER`/`IMAGE_PROVIDER` | `mock`（先省成本） |

⚠️ **密钥只信环境变量**；`.env.example.cloud` 只是模板，别填真实值后提交。

### 3) 首启建库
云函数首次部署后,手动触发一次:
```bash
# 在云函数本地/控制台 shell 执行一次,幂等
python -c "from cloud_deploy.bootstrap_schema import run; print(run())"
```
会在 MySQL 上建表并提升 `ADMIN_USERNAME` 管理员。已存在则幂等不重复。

### 4) 配置 HTTP 触发器
「云函数 → 触发管理 → 创建触发器，类型 HTTP」。得到公网 URL 如
`https://xxx.service.tcloudbase.com`。之后所有 `/api/*` 都走该 URL。

---

## 四、把前端 / EXE 指向云端

你在 `config.py` / `.env` 里把后端地址指向云函数 URL（不是本地 `localhost:8000`）。
- Web 前端 BFF: `BACKEND_URL=https://<云函数公网URL>`。
- 桌面 EXE 打包时,**只打包 UI 壳 + 服务器地址**，不打包任何 DB/Key（关键）。

---

## 五、安全性自检清单（防破解）

- [ ] 代码库 / Git 里搜索 `sk-`、`hunyuan`、`TENCENT` —— 应为空（只存在于 CloudBase 环境变量）。
- [ ] EXE 内`strings`导出不含任何 Key、不含数据库 SQL。
- [ ] `AUTH_SECRET` 已随机化；`ADMIN_USERNAME` 已设且非默认弱口令。
- [ ] 兑换码/余额只在云端 mint/redeem；EXE 不本地生成。
- [ ] 生产用 `AUTH_REQUIRED=true`：所有 /api/credits·orders·mine 需 Bearer。

---

## 六、混元 LLM 说明（零代码新增）
现有 `provider.py` 的 `OpenAICompatLLMProvider` 直接支持 OpenAI 兼容端点。
切换到混元 = 只需改 `LLM_PROVIDER=openai_compat` + `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL`，
LAN 本地则：不回落。全部 LLM 生成都在云函数进程内发起，绝不出云。
