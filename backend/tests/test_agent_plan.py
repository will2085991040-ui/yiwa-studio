"""Step 4 测试：AgentPlan 契约（结构化输出兼容 + Schema 级 DAG 校验）。"""
import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.base import registry
from app.schemas.agent_plan import (
    VALID_AGENT_TYPES,
    AgentPlan,
    PlanBudget,
    plan_json_schema,
)


def _task(task_id, agent_type, objective, deps=None, out=None):
    return {
        "id": task_id,
        "agent_type": agent_type,
        "objective": objective,
        "dependencies": deps or [],
        "output_schema": out or {"type": "object", "properties": {}},
    }


def otome_plan() -> dict:
    """乙女悬疑互动短剧：World -> Character -> Relationship -> Plot -> Scene -> Branch -> Dialogue -> Evaluation。"""
    return {
        "goal": "制作一个乙女悬疑互动短剧，3个男主，恋爱+悬疑双线，5章，3个结局",
        "goal_summary": "乙女向悬疑恋爱双线互动短剧",
        "project_type": "interactive_short_drama",
        "target_audience": "喜欢乙女游戏与悬疑剧的年轻女性用户",
        "genre": "乙女 / 悬疑 / 恋爱",
        "tone": "甜宠中带悬疑张力，暧昧与反转并重",
        "business_objective": "提升互动剧转化与留存",
        "creative_objective": "让玩家沉浸于多男主感情线与身份谜团",
        "required_capabilities": [
            "worldbuilding", "character", "relationship", "story",
            "scene", "branch", "dialogue", "evaluation",
        ],
        "characters_required": "1 女主 + 3 男主（其中一人隐藏真实身份）",
        "worldbuilding_required": "娱乐公司职场 + 悬疑世界观",
        "story_required": "恋爱线与悬疑线双线交织，分 5 章",
        "scene_required": "每章关键互动场景",
        "branch_required": "3 个结局 + 多分支",
        "dialogue_required": "多角色对话，防 OOC",
        "evaluation_required": "质量 / 沉浸度 / 一致性评测",
        "generation_steps": [
            _task(
                "t1", "world", "构建娱乐公司与悬疑世界观",
                out={"type": "object", "properties": {"world": {"type": "object"}}},
            ),
            _task("t2", "character", "设计 1 女主 + 3 男主角色卡", deps=["t1"]),
            _task("t3", "relationship", "设计角色关系图与情感/悬疑关系", deps=["t2"]),
            _task("t4", "plot", "规划恋爱+悬疑双线主线（5 章）", deps=["t2", "t3"]),
            _task("t5", "scene", "拆分为互动场景卡", deps=["t4"]),
            _task("t6", "branch", "设计互动分支与 3 个结局", deps=["t5"]),
            _task("t7", "dialogue", "生成多角色对话", deps=["t5"]),
            _task("t8", "evaluation", "评测质量/沉浸度/一致性", deps=["t6", "t7"]),
        ],
        "success_metrics": ["玩家选择深度", "结局达成率", "悬疑线揭示满足度"],
        "constraints": ["单章对白 ≤ 2000 token", "角色不 OOC"],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": 2.0},
        "priority": "high",
    }


def test_valid_film_plan_roundtrips():
    plan = AgentPlan.model_validate(otome_plan())
    again = AgentPlan.model_validate_json(plan.model_dump_json())
    assert again == plan
    # 生产链：World -> Character -> Relationship -> Plot -> Scene -> Branch/Dialogue -> Evaluation
    assert [s.agent_type for s in plan.generation_steps] == [
        "world", "character", "relationship", "plot", "scene", "branch", "dialogue", "evaluation",
    ]
    # 关键依赖关系真实表达（story 能力由 plot agent 承担）
    assert {s.id: s.dependencies for s in plan.generation_steps}["t4"] == ["t2", "t3"]


def test_empty_generation_steps_rejected():
    payload = otome_plan()
    payload["generation_steps"] = []
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_unknown_agent_type_rejected():
    payload = otome_plan()
    payload["generation_steps"][0]["agent_type"] = "story"  # 非注册 agent 名（story 由 plot 承担）
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_duplicate_task_id_rejected():
    payload = otome_plan()
    payload["generation_steps"][1]["id"] = "t1"
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_missing_dependency_rejected():
    payload = otome_plan()
    payload["generation_steps"][2]["dependencies"] = ["nonexistent"]
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_self_dependency_rejected():
    payload = otome_plan()
    payload["generation_steps"][0]["dependencies"] = ["t1"]
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_dependency_cycle_rejected():
    payload = otome_plan()
    payload["generation_steps"] = [
        _task("a", "plot", "x", deps=["b"]),
        _task("b", "scene", "y", deps=["a"]),
    ]
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_invalid_plan_budget_rejected():
    with pytest.raises(ValidationError):
        PlanBudget(max_total_tokens=0)
    payload = otome_plan()
    payload["budget"] = {"max_total_tokens": 0}
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_invalid_task_budget_rejected():
    payload = otome_plan()
    payload["generation_steps"][0]["budget"] = {"max_output_tokens": 0}
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_invalid_priority_rejected():
    payload = otome_plan()
    payload["priority"] = "urgent"
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)
    payload = otome_plan()
    payload["generation_steps"][0]["priority"] = "urgent"
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_invalid_condition_rejected():
    payload = otome_plan()
    payload["generation_steps"][0]["condition"] = "   "
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_invalid_output_schema_rejected():
    payload = otome_plan()
    payload["generation_steps"][0]["output_schema"] = {"type": "wat"}
    with pytest.raises(ValidationError):
        AgentPlan.model_validate(payload)


def test_json_schema_valid_and_feeds_structured_output():
    """结构化输出兼容：AgentPlan 的 model_json_schema() 是合法 JSON Schema，且示例数据双向通过。"""
    schema = plan_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)  # 本身是合法 JSON Schema
    assert schema["type"] == "object"
    jsonschema.validate(otome_plan(), schema)             # 示例数据满足自身 Schema（Provider 输出可据此校验）
    plan = AgentPlan.model_validate(otome_plan())         # 且通过 Pydantic 语义校验
    assert plan.goal.startswith("制作")


def test_agent_types_match_registry():
    registered = {a["name"] for a in registry.list()}
    # finalize 由 Orchestrator 确定性执行（编译/质检收尾，非 LLM Agent），不在 registry 登记
    assert VALID_AGENT_TYPES == registered | {"finalize"}