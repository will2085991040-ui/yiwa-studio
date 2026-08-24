# AI Interactive Growth Agent · 架构设计（V2.0 摘要版）

> 完整设计见《技术架构设计 V2.0》（本仓库开发历史）。本文档是代码的事实依据。

## 1. 产品定位

**输入一个业务/营销/内容目标 → 自动生成并运行一个专业 Agent。**

- 不是聊天机器人 / 角色扮演 / 小说生成器的拼装；
- 是「Agent 工厂 + Agent 运行时 + Agent 优化系统」：`Agent Creation → Generation → Runtime → Learning → Optimization`；
- 互动叙事（世界/角色/剧情/分支）是**内容基础设施**，增长闭环是**第一目标**。

## 2. 核心概念

| 概念 | 定义 |
|---|---|
| **AgentSpec** | 一个 Agent 是什么的机器可读定义（identity/goal/audience/strategy/funnel/characters/relationships/world/story/interaction_graph/state_machine/tools/knowledge/memory/runtime/evaluation/optimization/budget/safety/version） |
| **Agent Compiler** | AgentSpec → Validation → Dependency Resolution → Prompt Assembly → Graph/Tool/Memory/Knowledge 校验 → Runtime 配置 → 可执行 Agent（后续 Phase 逐步实现） |
| **Interaction Graph** | 剧情+对话+用户行为+工具调用+CTA 的统一执行图（节点类型：message/choice/question/tool_call/api_call/character_switch/memory_write/knowledge_retrieval/cta/task/condition/branch/end；预留 form/mini_game/external_page/handoff） |
| **User State Machine** | NEW→ENGAGED→INTERESTED→TRUSTED→INTENT→CONVERTED→RETAINED（+CHURN_RISK 软标记），迁移由规则定义 |
| **Golden Path** | 自然语言目标 → Director → AgentSpec → Compiler → Validation → Ready → Playground → Runtime → Analytics → Evaluation → Optimization |

## 3. 五层 Agent 体系（14 Agent + 4 确定性引擎）

```
L1 编排      Director（Agent Architect）
L2 增长      Audience / Strategy / Funnel
L3 内容      World / Character / Relationship / Plot / Branch / Scene / Dialogue
L4 互动执行   Interaction（决策者） / Runtime
L5 增长优化   Analytics / Evaluation / Optimization / Experiment
确定性引擎    State Engine · Consistency Engine · Memory System · Tool Executor
```

## 4. 角色卡（业务化，驱动 Runtime）

`identity / appearance / personality / background / psychology(goal·motivation·fear·values·belief) /
behavior / language / knowledge_bounds / memory_policy / relationship_policy / interaction_policy /
conversion_role(attention|trust|expert|sales|guide|comic_relief) / conversion_rules /
tool_permissions / allowed_topics / forbidden_topics / runtime_state / portrait`

- 修改角色卡 → Agent 实际行为必须改变（注入 Interaction Context 与 Runtime Policy）；
- 角色切换 = State Engine 硬约束（如 sales 角色要求 stage≥INTENT）+ Interaction Agent 软决策。

## 5. 运行时核心循环

```
用户消息 → 意图识别 → 合法性校验(条件/可达/stage) → Context Builder(最小必要上下文)
→ Interaction Agent 决策(聊天/提问/切角色/CTA/工具/结束) → Dialogue(多角色,防OOC)
→ State Engine 结算(effects/关系迁移/stage迁移/flags) → 下一节点 → 持久化 → SSE 流式返回
```

## 6. 横切能力

- **Memory**：short_term/long_term/episodic/character/user/business 六类；importance/confidence/source/timestamp/expiration/privacy_scope；pgvector 语义检索；
- **RAG**：解析→分块→Embedding→pgvector→检索→Context Builder；知识范围受 knowledge_bounds 约束；
- **MCP**：官方 SDK client + 注册表 + 工具白名单（默认关闭）；自带示例 server（后续 Phase）；
- **Tool**：ToolRegistry/ToolExecutor/ToolPermission/ToolSchema/ToolResult/ToolTrace；JSON Schema + 超时 + 重试 + 成本；
- **Budget**：每次调用记录 token/成本；项目/Agent/会话三级预算，超限降级；
- **Trace**：agent_runs → agent_steps → tool_calls 全量落库，可回放；
- **Evaluation**：规则 + LLM-as-Judge，输出 Agent Health Score（任务/对话质量/一致性/工具/知识接地/互动正确/参与/转化/留存/成本/延迟）；
- **Optimization**：提案 → 人工审批或 A/B → Evaluation → 发布/回滚（禁止全自动改线上）；
- **锁定资产**：Character/Prompt/Graph/Strategy 可 locked=true，Optimization 必须尊重。
- **Billing（计费/充值）**：引擎级点数计费——请求级上下文(Async ContextVar)对 Agent 调用精准记费，兑换码充值、余额可为负、全量流水可溯源。细节见 `docs/billing-architecture.md`。

## 7. 数据模型（Phase 0 已建）

`projects / agent_specs / agent_versions / agent_runs / agent_steps`
（后续 Phase 增加 worlds/characters/relationships/funnels/interaction_graphs/user_profiles/user_events/memories/knowledge_*/tool_*/evaluation_*/experiments 等）

## 8. 技术栈

Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL+pgvector · LangGraph(编排，后续 Phase) ·
Next.js 14 · TypeScript · Tailwind · React Flow(后续 Phase) · Docker Compose · pytest · GitHub Actions

## 9. Phase 路线（Golden Path 优先）

Phase 0 骨架(本阶段) → LLM Provider → Director → Growth 三 Agent → 内容 Agent → Interaction Graph+State → Tool/MCP → Runtime+Dialogue → Memory → RAG → Analytics → Evaluation → Trace UI → Optimization/Experiment → 前端全页 → Docker → 全量测试+3 Demo → 文档
