# Career Capability Matrix

> 诚实记录：`implemented` 表示当前已真实可运行，`planned` 表示尚未实现（未来 Step 落地）。

## Prompt Engineering / Versioning

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Prompt 定义（稳定引用键） | implemented | `PromptDefinition`（name 唯一，如 `character_generation`） |
| Prompt 版本化 | implemented | `PromptVersion` v1/v2 追加式演进，不可原地修改 |
| Prompt 变量声明与渲染 | implemented | `PromptVariable` + `services.prompts.render()`（required/default 语义） |
| Agent 绑定 PromptVersion | implemented | WorldAgent/CharacterAgent 经 `render()` → `LLMRequest(prompt_version=...)` 落地 |
| Prompt A/B 测试 | planned | 依赖 Optimization Agent 后续 Step |

## Agent Planning / Orchestration

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| AgentPlan 结构化计划契约 | implemented | `AgentPlan`（Pydantic + JSON Schema + generation_steps 任务 DAG + Schema 级校验） |
| Director Agent | implemented | Step 5：自然语言 → Director → `AgentPlan` |
| DAG 执行器 | implemented | Step 6：任务依赖图的运行时调度（world→character 数据流转） |
| WorldAgent | implemented | Step 6：创意 + 计划 → 结构化 WorldBible Artifact |
| CharacterAgent | implemented | Step 7：WorldBible + 创意 → 结构化 CharacterCard Artifact |
| RelationshipAgent | implemented | Step 9：WorldBible + CharacterCard → 结构化 RelationshipGraph Artifact |
| PlotAgent / StoryAgent | implemented | Step 10：WorldBible + CharacterCard + RelationshipGraph → 互动剧情图 StoryGraph Artifact |

## Interactive Creation Layer（Step 8）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Artifact 版本体系 | implemented | version / parent_version / source / change_reason / is_latest（Git 式，旧版本不覆盖） |
| 项目工作区 | implemented | Project 增加 title / description / current_version |
| 用户修改流 | implemented | `POST /projects/{id}/revise`：User Request → 对应 Agent → Artifact v2 |
| 局部执行 | implemented | `POST /projects/{id}/tasks/{tid}/run`：单任务重跑（非 Whole Project） |
| 版本历史读取 | implemented | `GET /projects/{id}/artifacts`（含被替换的旧版本） |
| Story Graph Schema | implemented | `StoryNode/StoryEdge/StoryVariable/Choice/StoryEffect`（仅 Schema） |
| Story Graph Runtime | planned | Step 13：条件/变量/状态求值引擎（Choice/Runtime） |

## Relationship Layer（Step 9）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| RelationshipGraph Schema | implemented | `RelationshipEdge/RelationshipChange` + 复用 `StoryEffect`（affection/trust/hostility/possible_changes） |
| upstream task_id 化 | implemented | 依赖输出按 `{task_id: {kind, content}}` 键化，支撑同 Agent 类型多任务（多角色/多场景/多对白） |
| 关系修订 | implemented | `revise` 支持 `relationship_graph` kind（用户修改关系 → v2） |
| 关系局部重跑 | implemented | `POST /tasks/{tid}/run` 支持 relationship 任务 |
| 关系图可视化 | implemented | 工作台渲染节点 + 关系边 + 状态 + 选择效果（结构化展示，非 React Flow） |
| React Flow 图形编辑器 | planned | 后续 Step：交互式剧情编辑器 |

## Story / Plot Layer（Step 10）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| StoryGraph 互动语义 | implemented | scene/choice/branch/ending 节点 + 边 + 变量 + 玩家选择效果（复用 Step8 StoryVariable/StoryEffect） |
| 剧情修改 | implemented | `revise` 支持 `story_graph` kind（用户修改剧情 → v2，旧版本保留） |
| 延长剧情 | implemented | `POST /projects/{id}/story {operation:"extend"}`：在每个未锁定场景叶节点后追加场景并连边（确定性图算法） |
| 增加分支 | implemented | `POST /projects/{id}/story {operation:"branch"}`：新增选择 + 分支场景 + 边 |
| 内容锁定 | implemented(字段预留) | `StoryNode.locked`；extend 跳过锁定叶、branch 拒绝锁定锚点（锁定修改 API 后续 Step） |
| 剧情图可视化 | implemented | 工作台渲染节点/选择/效果/锁定徽章（结构化展示） |
| SceneAgent 消费 | implemented | Step 11：消费 StoryGraph 逐节点本地生成可编辑场景正文 |
| DialogueAgent 消费 | planned | Step 12：消费 StoryGraph 生产对白 |

## Scene Layer（Step 11）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| SceneContent Schema | implemented | `scene_id/title/summary/location/time/atmosphere/characters_present/events/visual_direction/camera_direction/stage_direction/emotional_beats/state_changes/continuity_notes` + 预留 asset_requirements |
| SceneAgent（on-demand） | implemented | 消费 WorldBible + CharacterCard + RelationshipGraph + StoryGraph + 指定 node + 前后节点/选择/变量 + 用户意图 + locked → 单节点 SceneContent（不含对白） |
| 单节点场景生成 | implemented | `POST /projects/{id}/scene {operation:"generate"}` → `scene:{node_id}` Artifact v1 |
| 单节点场景修改 | implemented | `operation:"revise"` → v+1（source=user，change_reason=指令） |
| 单节点场景扩写 | implemented | `operation:"expand"` → v+1（追加事件节拍，source=user） |
| 按节点独立版本链 | implemented | Artifact kind=`scene:{node_id}`（scene:a 的 v2 不影响 scene:b）；kind 列 40→120 |
| 锁定节点保护 | implemented | 锁定 SceneNode 生成/修改/扩写一律 409 locked_node（不静默覆盖） |
| 场景可视化 | implemented | 工作台按节点选择并渲染场景卡 + 版本/来源徽章 |
| 资产需求（图/音/视频） | planned(字段预留) | SceneContent.asset_requirements，多模态 API 留待后续 Step |