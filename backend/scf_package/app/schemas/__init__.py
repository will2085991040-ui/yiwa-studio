"""Pydantic Schema：API 请求/响应（Agent 结构化输出的起点）。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent_plan import (  # noqa: F401 —— 再导出 Director 结构化输出契约
    VALID_AGENT_TYPES,
    AgentPlan,
    PlanBudget,
    ProductionTask,
    RetryPolicy,
    TaskBudget,
)


class GoalInput(BaseModel):
    """用户输入的自然语言目标。"""

    goal: str = Field(min_length=2, max_length=2000, description="你想让 Agent 帮你完成什么")
    game_type: Literal["galgame", "avg", "interactive_film"] | None = Field(
        default=None, description="作品类型：galgame / avg 文字 / interactive_film 互动影视"
    )
    title: str | None = Field(default=None, max_length=200, description="可选项目标题")


class PlanStep(BaseModel):
    key: str
    label: str
    description: str
    agent: str
    dependencies: list[str] = Field(default_factory=list)
    status: Literal[
        "pending", "ready", "running", "succeeded", "failed", "blocked", "skipped", "done"
    ] = "pending"
    reason: str = Field(default="")


class AgentSpecOut(BaseModel):
    id: str
    goal_summary: str
    template: str
    status: str
    plan: list[PlanStep]


class AgentVersionOut(BaseModel):
    id: str
    version_no: int
    label: str
    status: str
    created_at: datetime


class AgentCreated(BaseModel):
    """创建 Agent 的完整返回：项目 + Spec + 版本 + 计划。"""

    project_id: str
    goal: str
    template: str
    agent_spec: AgentSpecOut
    agent_version: AgentVersionOut


class ProjectOut(BaseModel):
    id: str
    goal: str
    template: str
    title: str
    description: str | None
    current_version: int
    status: str
    created_at: datetime


class WorkflowOut(BaseModel):
    project_id: str
    status: str
    steps: list[PlanStep]


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatOut(BaseModel):
    reply: str
    status: str
    template: str


class AgentStepOut(BaseModel):
    id: str
    seq: int
    agent: str
    step_key: str
    status: str
    latency_ms: int
    token_usage: dict
    error: str | None


class AgentRunOut(BaseModel):
    id: str
    kind: str
    status: str
    started_at: datetime
    steps: list[AgentStepOut]


class AgentDefinition(BaseModel):
    """Agent 注册表条目（控制台展示）。"""

    name: str
    layer: str
    description: str
    input_schema: dict
    output_schema: dict
    implemented: bool


class HealthOut(BaseModel):
    status: str
    version: str
    llm_provider: str
    agents_registered: int
    llm_mode: str = "mock"          # 实际生效的 LLM 模式（mock | openai_compat | yiwa_gateway）
    llm_fallback: bool = False       # 是否因配置无效而回退到离线 mock
    llm_note: str = ""               # 回退/模式说明（面向用户）


# ---------------------------------------------------------------------------
# Prompt 版本基础设施（Step 3）
# ---------------------------------------------------------------------------


class PromptVariable(BaseModel):
    """Prompt 模板中的单个变量声明（存为 PromptVersion.variables 的 JSON 列表）。"""

    name: str = Field(min_length=1, max_length=60)
    type: str = "text"  # text|enum|number|bool（Step 3 仅做 text 占位替换，预留类型）
    description: str = ""
    required: bool = False
    default: Any = None


class PromptDefinitionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80, description="稳定引用键，如 character_generation")
    description: str | None = None


class PromptDefinitionOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime


class PromptVersionCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    variables: list[PromptVariable] = Field(default_factory=list)
    model_preferences: dict = Field(default_factory=dict)
    status: Literal["draft", "active", "deprecated"] = "draft"


class PromptVersionOut(BaseModel):
    """只读、冻结：PromptVersion 一旦创建不可变。"""

    model_config = ConfigDict(frozen=True)

    id: str
    prompt_definition_id: str
    version_no: int
    content: str
    variables: list[PromptVariable]
    model_preferences: dict
    status: str
    created_at: datetime


class PromptRenderInput(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)


class PromptRenderOut(BaseModel):
    prompt_id: str
    prompt_version: int
    rendered: str
    used_variables: dict[str, Any]


# ---------------------------------------------------------------------------
# Director 垂直切片（Step 5）
# ---------------------------------------------------------------------------


class DirectorPlanOut(BaseModel):
    """Director 规划成功后的完整返回：项目 + AgentPlan + 版本 + LLM 元信息。"""

    project_id: str
    goal: str
    prompt_version: str
    provider: str
    model: str
    latency_ms: int
    agent_plan: dict
    agent_version: AgentVersionOut


class DirectorPlanView(BaseModel):
    """按 project_id 读取已持久化的 Director 规划。"""

    project_id: str
    goal: str
    prompt_version: str
    provider: str
    model: str
    agent_plan: dict


# ---------------------------------------------------------------------------
# Orchestrator（Step 6）
# ---------------------------------------------------------------------------


class ArtifactOut(BaseModel):
    id: str
    task_id: str
    agent: str
    kind: str
    content: dict
    prompt_version: str
    version: int
    parent_version: int | None
    source: str
    change_reason: str | None
    is_latest: bool


class OrchestrationOut(BaseModel):
    project_id: str
    status: str
    steps: list[PlanStep]
    artifacts: list[ArtifactOut]


# ---------------------------------------------------------------------------
# Interactive Creation Layer（Step 8）：用户持续修改 / 局部执行
# ---------------------------------------------------------------------------


class RevisionInput(BaseModel):
    """用户对某一类 Artifact 的修改请求。"""

    kind: str = Field(min_length=1, max_length=40, description="如 world_bible / character_card")
    instruction: str = Field(min_length=1, max_length=2000, description="修改要求（如 让女主更傲娇）")


# ---------------------------------------------------------------------------
# Story 结构操作（Step 10）：延长剧情 / 增加分支
# ---------------------------------------------------------------------------


class StoryOperationInput(BaseModel):
    """对 StoryGraph 的确定性结构操作（非 LLM 生成）。"""

    operation: Literal["extend", "branch"] = Field(description="extend=延长剧情 / branch=增加分支")
    instruction: str = Field(min_length=1, max_length=2000, description="操作意图（会记为 change_reason 与新节点摘要）")
    anchor_node_id: str | None = Field(default=None, max_length=80, description="branch 的锚点节点（默认 entry）")
    count: int = Field(default=3, ge=1, le=20, description="extend 在每个叶节点后追加的场景数")


# ---------------------------------------------------------------------------
# Scene 局部操作（Step 11）：按节点生成 / 修改 / 扩写场景
# ---------------------------------------------------------------------------


class SceneOperationInput(BaseModel):
    """对 StoryGraph 单个 SceneNode 的场景内容操作。"""

    operation: Literal["generate", "revise", "expand"] = Field(description="generate=生成 / revise=修改 / expand=扩写")
    node_id: str = Field(min_length=1, max_length=80, description="目标 StoryGraph 节点 id")
    instruction: str = Field(default="", max_length=2000, description="revise/expand 的用户要求")


# ---------------------------------------------------------------------------
# Dialogue 局部操作（Step 12）：按 (node_id, choice_id) 生成 / 修改 / 扩写对白
# ---------------------------------------------------------------------------


class DialogueOperationInput(BaseModel):
    """对 StoryGraph 单个 (node_id, choice_id) 的对白内容操作。"""

    operation: Literal["generate", "revise", "expand"] = Field(description="generate=生成 / revise=修改 / expand=扩写")
    node_id: str = Field(min_length=1, max_length=80, description="目标 StoryGraph 节点 id")
    choice_id: str | None = Field(default=None, max_length=80, description="节点内选择 id；None 表示节点默认/开场对白")
    instruction: str = Field(default="", max_length=2000, description="revise/expand 的用户要求")


# ---------------------------------------------------------------------------
# Runtime（Step 13）：互动游玩会话 / 状态推进最小闭环
# ---------------------------------------------------------------------------


class RuntimeSessionOut(BaseModel):
    session_id: str
    project_id: str
    current_node_id: str
    state: dict
    created_at: datetime


class RuntimeChoiceOut(BaseModel):
    choice_id: str
    text: str
    condition: str | None
    effects: list[dict]
    next_node: str | None


class ChoiceInput(BaseModel):
    choice_id: str = Field(min_length=1, max_length=80)


# ---------------------------------------------------------------------------
# Version Governance（Step 14）：compare / promote / revert
# ---------------------------------------------------------------------------


class ArtifactCompareInput(BaseModel):
    kind: str = Field(min_length=1, max_length=220, description="如 story_graph / character_card")
    version_a: int = Field(ge=1, description="基线版本号")
    version_b: int = Field(ge=1, description="对比版本号")


class ArtifactVersionInput(BaseModel):
    kind: str = Field(min_length=1, max_length=220)
    version: int = Field(ge=1, description="目标版本号")
    expected_latest: int | None = Field(default=None, ge=1, description="乐观并发校验：期望的当前 latest 版本号")


class ArtifactCompareOut(BaseModel):
    version_a: int
    version_b: int
    content_diff: dict
    metadata_diff: dict


class ArtifactGovernanceOut(BaseModel):
    kind: str
    version: int
    is_latest: bool
    parent_version: int | None
    source: str
    change_reason: str | None


# ---------------------------------------------------------------------------
# Context Compiler（Step 15）：统一上下文装配入口
# ---------------------------------------------------------------------------


class ContextCompileInput(BaseModel):
    focus_node_id: str | None = Field(default=None, max_length=80)
    focus_choice_id: str | None = Field(default=None, max_length=80)
    instruction: str = Field(default="", max_length=2000)
    token_budget: int | None = Field(default=None, ge=1)
    runtime_state: dict | None = None


class ContextCompileOut(BaseModel):
    project_id: str
    layers: dict
    missing: list[str]
    token_estimate: int
    trimmed: list[str]


# ---------------------------------------------------------------------------
# Creative Action + HITL（Step 16）：统一动作生命周期
# ---------------------------------------------------------------------------


class CreativeActionInput(BaseModel):
    operation: str = Field(min_length=1, max_length=40)
    source: Literal["chat", "button", "node", "choice", "artifact", "storygraph"] = "chat"
    kind: str = Field(default="", max_length=220)
    payload: dict = Field(default_factory=dict)
    node_id: str | None = Field(default=None, max_length=80)
    choice_id: str | None = Field(default=None, max_length=80)


class ActionOut(BaseModel):
    status: str  # pending | executed | rejected
    proposal_id: str | None = None
    artifact: dict | None = None
    state: dict | None = None
    governance: dict | None = None
    transaction_id: str | None = None


class ProposalOut(BaseModel):
    id: str
    project_id: str
    source: str
    operation: str
    kind: str
    risk: str
    status: str


# ---------------------------------------------------------------------------
# Skill System（Step 17）
# ---------------------------------------------------------------------------


class SkillCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    instructions: str = ""
    source: Literal["project", "user"] = "project"
    enabled: bool = True
    priority: int = 0
    forced: bool = False
    is_default: bool = False


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    instructions: str
    version: int
    source: str
    enabled: bool
    priority: int
    forced: bool
    is_default: bool


# ---------------------------------------------------------------------------
# Branch（Step 18）：分支一等公民
# ---------------------------------------------------------------------------


class BranchCreateInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    plan: dict = Field(default_factory=dict)
    base_version: int | None = Field(default=None, ge=1)
    parent_branch_id: str | None = None
    current_node_id: str | None = Field(default=None, max_length=80)
    state: dict = Field(default_factory=dict)


class BranchOut(BaseModel):
    id: str
    project_id: str
    parent_branch_id: str | None
    name: str
    description: str
    status: str
    base_version: int
    base_kind: str
    current_node_id: str | None
    state: dict
    is_selected: bool


class BranchCompareInput(BaseModel):
    branch_a_id: str
    branch_b_id: str


class BranchCompareOut(BaseModel):
    branch_a: str
    branch_b: str
    state_diff: dict
    plan_diff: dict
    base_version_a: int
    base_version_b: int
    current_node_diff: dict


class BranchSnapshotInput(BaseModel):
    content: dict = Field(default_factory=dict)
    change_reason: str | None = None


class BranchMergeInput(BaseModel):
    target_branch_id: str


class BranchVersionOut(BaseModel):
    id: str
    branch_id: str
    version_no: int
    kind: str
    content: dict
    change_reason: str | None


# ---------------------------------------------------------------------------
# Material（Step 19）：素材元数据 / 引用 / 检索
# ---------------------------------------------------------------------------


class MaterialCreateInput(BaseModel):
    kind: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    storage_path: str = ""
    mime_type: str = ""
    metadata: dict = Field(default_factory=dict)
    ref_kind: str = ""
    ref_id: str | None = Field(default=None, max_length=220)
    tags: list[str] = Field(default_factory=list)


class MaterialAssociateInput(BaseModel):
    ref_kind: str = Field(min_length=1, max_length=220)
    ref_id: str | None = Field(default=None, max_length=220)


class MaterialOut(BaseModel):
    id: str
    project_id: str
    kind: str
    name: str
    description: str
    storage_path: str
    mime_type: str
    metadata: dict
    ref_kind: str
    ref_id: str | None
    tags: list[str]
    status: str


# ---------------------------------------------------------------------------
# Play Runtime（Step 20）
# ---------------------------------------------------------------------------


class PlaySessionOut(BaseModel):
    id: str
    project_id: str
    world: dict
    status: str


class PlayTurnCreateInput(BaseModel):
    intent: str = ""
    mutation: dict = Field(default_factory=dict)


class PlayTurnOut(BaseModel):
    turn_id: str
    seq: int
    world: dict
    rendered: str
