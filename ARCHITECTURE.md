# YIWA Studio · Architecture 总览

> 一个仓库打通「LLM 应用 → 前端 → 后端 → 桌面打包」，并从 0 自建了一套引擎级点数计费。快速看这里,深挖看各子文档。

## 组件到文档导航

| 想得到 | 去 |
| --- | --- |
| 全局架构与 Agent 体系 | [docs/architecture.md](docs/architecture.md) |
| 点数计费怎么实现(含收费流图) | [docs/billing-architecture.md](docs/billing-architecture.md) |
| 能力矩阵(逐条 implemented/planned) | [docs/career-capability-matrix.md](docs/career-capability-matrix.md) |
| 怎么跑/打包 | README「启动」「打包」 |
| CI | .github/workflows/ci.yml (ruff + pytest + 前端 build) |

## 三大创新点(面试/评审直接讲)

1. **Agent 编排 + 结构化输出**:Director 把自然语言目标编译成 `AgentPlan`(Pydantic + JSON Schema + DAG 任务图),World/Character/Plot/Scene 等 Agent 按依赖图执行,层层产出机器可校验的结构化 Artifact,并可『锁定』后修改/扩写。
2. **引擎级点数计费(存量系统零侵入增量)**:Agent 内部深处才调 LLM、没有『用户』——用 `Async ContextVar`(请求作用域)把 user id 透传到最深结算点,在 LLM 结算帧加 best-effort 扣费钩子;引擎级单价×(成本/markup=40% 毛利)、兑换码充值、余额可为负只记流水、全量可溯源。既不给业务代码提侵入,也不漏记。
3. **双端/桌面交付**:同一 FastAPI 后端 + 静态导出 Next.js 前端,既能 Web 部署,又可打包为单文件 Windows EXE(PyWebView 内嵌),一套代码两端变现。

## 数据流(运行视角)

```
前端(Web/桌面) --HTTPS--> FastAPI(鉴权) --asyncio--> Agent 编排(orchestrate)
                                                      |
                                    导演/世界/角色/剧情/分镜 各 Agent
                                                      |
                                    Provider.generate() --拿到 usage--> charge_from_context
                                                      |                     |
                                                      |                     v
                                                      +----> credits.charge_for_usage(engine级→点数, 余额可为负, ledger入账)
```

## 质量
- ruff 全绿;80+ 后端测试(provider 契约 / 计费 / 鉴权 / 媒体 / 剧本链路);GitHub Actions 自动跑;前端静态导出可出镜像部署。

---
由本人独立开发与打包。