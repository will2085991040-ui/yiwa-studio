"""AgentPlan：Director 对 Multi-Agent 互动影视/游戏生产管线的结构化计划契约。

用途（Step 5 真正接入）：
    Director -> LLMProvider.generate_structured(json_schema=AgentPlan.model_json_schema())
             -> AgentPlan（Pydantic 校验）

generation_steps 是结构化 Task 的 DAG：
- agent_type 与 app.agents.catalog 注册名一致（world/character/relationship/plot/...）
- dependencies 引用其他 task id，形成依赖图（Director 理解"一个 Agent 依赖另一个的输出"）
- 每个 task 声明 output_schema（其 Agent 的结构化输出契约）、priority、retry_policy、budget、condition

本步只做 Schema 级校验（未知 agent / 依赖缺失 / 环 / 重复 id / 空 steps / 预算 / 优先级 /
条件 / output_schema）。真正的 DAG 执行器与运行时验证留到后续 Step。
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# 与 app.agents.catalog 注册名保持一致（测试同步校验）。
# 语义说明："story/worldbuilding" 能力由注册的 plot/world Agent 承担。
VALID_AGENT_TYPES: frozenset[str] = frozenset(
    {
        "director", "audience", "strategy", "funnel", "world", "character",
        "relationship", "plot", "branch", "scene", "dialogue", "interaction",
        "runtime", "analytics", "evaluation", "optimization", "experiment",
        "storyboard", "finalize",
    }
)

_JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}

Priority = Literal["low", "medium", "high", "critical"]
OnError = Literal["retry", "repair", "fallback", "abort"]


class RetryPolicy(BaseModel):
    """任务级重试策略（确定性，运行时执行）。"""

    max_retries: int = Field(default=2, ge=0, le=10)
    backoff_seconds: float = Field(default=0.5, ge=0)
    on_error: OnError = "retry"


class TaskBudget(BaseModel):
    """任务级预算。"""

    max_output_tokens: int = Field(default=2048, ge=1, le=100_000)
    max_duration_seconds: float | None = Field(default=None, ge=0)


class ProductionTask(BaseModel):
    """生产管线中的一个结构化任务节点（DAG 顶点）。"""

    id: str = Field(min_length=1, max_length=80)
    agent_type: str = Field(min_length=1, max_length=40)
    objective: str = Field(min_length=1, max_length=2000)
    input_refs: list[str] = Field(default_factory=list)          # 数据流引用（task id 或符号输入，如 "goal"）
    output_schema: dict[str, Any] = Field(default_factory=dict)  # 该 Agent 必须满足的 JSON Schema
    dependencies: list[str] = Field(default_factory=list)        # 必须完成的 task id（控制流）
    priority: Priority = "medium"
    condition: str | None = Field(default=None, max_length=500)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    budget: TaskBudget = Field(default_factory=TaskBudget)

    @field_validator("id")
    @classmethod
    def _id_no_whitespace(cls, value: str) -> str:
        if any(ch.isspace() for ch in value):
            raise ValueError("task id 不能包含空白字符")
        return value

    @field_validator("agent_type")
    @classmethod
    def _known_agent(cls, value: str) -> str:
        if value not in VALID_AGENT_TYPES:
            raise ValueError(f"未知 agent_type：{value}")
        return value

    @field_validator("condition")
    @classmethod
    def _condition_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("condition 不能为空白字符串")
        return stripped

    @field_validator("dependencies", "input_refs")
    @classmethod
    def _unique_refs(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("依赖/输入引用列表不能存在重复项")
        return value


class PlanBudget(BaseModel):
    """计划级全局预算（确定性上限）。"""

    max_total_tokens: int = Field(default=100_000, ge=1, le=100_000_000)
    max_cost_usd: float | None = Field(default=None, ge=0)


class AgentPlan(BaseModel):
    """Director 的结构化计划输出：一次性描述整个互动影视/游戏生产管线。"""

    goal: str = Field(min_length=2, max_length=2000)
    goal_summary: str = Field(min_length=1, max_length=300)
    project_type: str = Field(min_length=1, max_length=60)
    target_audience: str = Field(min_length=1, max_length=300)
    genre: str = Field(min_length=1, max_length=120)
    tone: str = Field(min_length=1, max_length=120)
    business_objective: str = Field(default="", max_length=500)
    creative_objective: str = Field(default="", max_length=500)
    required_capabilities: list[str] = Field(default_factory=list)
    characters_required: str = Field(default="", max_length=2000)
    worldbuilding_required: str = Field(default="", max_length=2000)
    story_required: str = Field(default="", max_length=2000)
    scene_required: str = Field(default="", max_length=2000)
    branch_required: str = Field(default="", max_length=2000)
    dialogue_required: str = Field(default="", max_length=2000)
    evaluation_required: str = Field(default="", max_length=2000)
    generation_steps: list[ProductionTask]
    success_metrics: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    budget: PlanBudget = Field(default_factory=PlanBudget)
    priority: Priority = "medium"

    @field_validator("required_capabilities")
    @classmethod
    def _capabilities_unique_nonempty(cls, value: list[str]) -> list[str]:
        cleaned = [c.strip() for c in value]
        if any(not c for c in cleaned):
            raise ValueError("required_capabilities 不能包含空字符串")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("required_capabilities 不能存在重复项")
        return cleaned

    @model_validator(mode="after")
    def _validate_generation_steps(self) -> "AgentPlan":
        steps = self.generation_steps
        if not steps:
            raise ValueError("generation_steps 不能为空")
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"generation_steps 存在重复 task id：{dup}")
        known = set(ids)
        for s in steps:
            for dep in s.dependencies:
                if dep == s.id:
                    raise ValueError(f"任务 {s.id} 不能依赖自身")
                if dep not in known:
                    raise ValueError(f"任务 {s.id} 的依赖 {dep} 不存在")
        self._check_no_cycles(steps)
        for s in steps:
            _validate_output_schema(s.id, s.output_schema)
        return self

    @staticmethod
    def _check_no_cycles(steps: list[ProductionTask]) -> None:
        white, gray, black = 0, 1, 2
        deps = {s.id: s.dependencies for s in steps}
        color = {s.id: white for s in steps}

        def visit(node: str, stack: list[str]) -> None:
            color[node] = gray
            for dep in deps[node]:
                if color[dep] == gray:
                    raise ValueError(f"generation_steps 存在依赖环：{' -> '.join(stack + [node, dep])}")
                if color[dep] == white:
                    visit(dep, stack + [node])
            color[node] = black

        for node in deps:
            if color[node] == white:
                visit(node, [])


def _validate_output_schema(task_id: str, schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"任务 {task_id} 的 output_schema 必须是 JSON Schema 对象")
    if "type" in schema and schema["type"] not in _JSON_TYPES:
        raise ValueError(f"任务 {task_id} 的 output_schema.type 非法：{schema['type']}")


def plan_json_schema() -> dict:
    """返回可作为 LLMProvider.generate_structured(json_schema=...) 输入的 JSON Schema。"""
    return AgentPlan.model_json_schema()