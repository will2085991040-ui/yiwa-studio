"""Step 5 测试：Director Agent 垂直切片（真实可跑通的开源链路，Mock 不绕过 Director）。"""
import asyncio
import json

import pytest

from app.agents.director import DirectorAgent
from app.core.errors import AppError
from app.llm.provider import MockProvider
from app.llm.types import LLMError, LLMProviderError, LLMResponse, TokenBudget
from app.schemas.agent_plan import AgentPlan
from app.services.prompt_seed import ensure_director_prompt
from app.trace.manager import trace_manager

GOLDEN_GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


class FakeProvider(MockProvider):
    """可编程 Provider：按队列返回 LLMResponse / 异常，并捕获收到的 LLMRequest。"""

    name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.captured: list = []

    async def _generate_structured(self, request):
        self.captured.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return LLMResponse(content=json.dumps(item, ensure_ascii=False), data=item)
        return item


def plan_dict(goal=GOLDEN_GOAL) -> dict:
    def t(i, a, o, deps=None):
        return {"id": i, "agent_type": a, "objective": o, "dependencies": deps or [],
                "output_schema": {"type": "object", "properties": {}}}

    return {
        "goal": goal, "goal_summary": goal, "project_type": "galgame", "target_audience": "乙女用户",
        "genre": "乙女悬疑", "tone": "甜宠悬疑", "business_objective": "", "creative_objective": "",
        "required_capabilities": [
            "worldbuilding", "character", "relationship", "story",
            "scene", "branch", "dialogue", "evaluation",
        ],
        "characters_required": "3 男主", "worldbuilding_required": "", "story_required": "", "scene_required": "",
        "branch_required": "", "dialogue_required": "", "evaluation_required": "",
        "generation_steps": [
            t("s1", "world", "世界观"), t("s2", "character", "角色", ["s1"]), t("s3", "relationship", "关系", ["s2"]),
            t("s4", "plot", "主线", ["s2", "s3"]), t("s5", "scene", "场景", ["s4"]), t("s6", "branch", "分支", ["s5"]),
            t("s7", "dialogue", "对白", ["s5"]), t("s8", "evaluation", "评测", ["s6", "s7"]),
        ],
        "success_metrics": ["选择深度"], "constraints": [],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None}, "priority": "high",
    }


@pytest.fixture()
def dir_ctx(session_factory):
    session = session_factory()
    ensure_director_prompt(session)
    run = trace_manager.start_run(session, kind="director_plan")
    yield session, run
    session.close()


def run_director(session, run, goal, provider, max_attempts=3, budget=None):
    agent = DirectorAgent(max_attempts=max_attempts)
    kwargs = {"session": session, "run": run, "goal": goal, "provider": provider}
    if budget is not None:
        kwargs["budget"] = budget
    return asyncio.run(agent.run(kwargs))


def test_director_endpoint_mock_golden_scenario(client):
    resp = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["prompt_version"] == "director_planning:v1"
    assert data["provider"] == "mock"
    assert data["agent_plan"]["goal"] == GOLDEN_GOAL
    steps = data["agent_plan"]["generation_steps"]
    agents = [s["agent_type"] for s in steps]
    for expected in ["world", "character", "relationship", "plot", "scene", "dialogue", "finalize"]:
        assert expected in agents
    assert any(s.get("dependencies") for s in steps)  # 存在真实依赖关系
    # GET 视图回读持久化的 AgentPlan
    pid = data["project_id"]
    view = client.get(f"/api/director/plan/{pid}")
    assert view.status_code == 200
    assert view.json()["agent_plan"] == data["agent_plan"]
    # Trace：director_plan run 记录完整步骤链
    traces = client.get(f"/api/projects/{pid}/traces").json()
    run = next(t for t in traces if t["kind"] == "director_plan")
    keys = [s["step_key"] for s in run["steps"]]
    for k in ["director.input", "llm.request", "llm.response", "validation", "final_plan"]:
        assert k in keys


def test_director_uses_structured_output_and_budget(dir_ctx):
    session, run = dir_ctx
    fake = FakeProvider([plan_dict()])
    budget = TokenBudget(max_input_tokens=8192, max_output_tokens=4096, max_total_tokens=12288)
    result = run_director(session, run, GOLDEN_GOAL, fake, max_attempts=1, budget=budget)
    req = fake.captured[0]
    assert req.json_schema["title"] == "AgentPlan"       # 走 generate_structured + AgentPlan schema
    assert req.prompt_version == "director_planning:v1"  # PromptVersion 绑定
    assert req.temperature == 0.3                        # 来自 PromptVersion.model_preferences
    assert req.budget == budget                          # 预算真正传入
    assert result["attempts"] == 1
    assert isinstance(result["agent_plan"], AgentPlan)


def test_director_repairs_invalid_plan_then_succeeds(dir_ctx):
    session, run = dir_ctx
    bad = plan_dict()
    bad["generation_steps"][0]["agent_type"] = "story"  # 语义非法（story 非注册 agent 名）
    fake = FakeProvider([bad, plan_dict()])
    result = run_director(session, run, GOLDEN_GOAL, fake, max_attempts=3)
    assert result["attempts"] == 2
    assert result["agent_plan"].generation_steps[0].agent_type == "world"


def test_director_invalid_plan_fails_cleanly(dir_ctx):
    session, run = dir_ctx
    bad = plan_dict()
    bad["generation_steps"] = []  # 空 steps，始终无法通过 Pydantic 语义校验
    fake = FakeProvider([bad, bad, bad])
    with pytest.raises(AppError) as exc:
        run_director(session, run, GOLDEN_GOAL, fake, max_attempts=2)
    assert exc.value.code == "plan_invalid"


def test_director_provider_error_fails_cleanly(dir_ctx):
    session, run = dir_ctx
    err = LLMProviderError(
        LLMError(code="timeout", message="请求超时", provider="fake", model="fake-model", retryable=True)
    )
    fake = FakeProvider([err])
    with pytest.raises(AppError) as exc:
        run_director(session, run, GOLDEN_GOAL, fake, max_attempts=1)
    assert exc.value.code == "director_llm_error"
    assert "超时" in exc.value.message


def test_director_budget_token_limit_surfaced(dir_ctx):
    """预算真正生效：输入超过预算时 Provider 抛 token_limit，Director 干净暴露为 director_llm_error。"""
    session, run = dir_ctx
    tiny = TokenBudget(max_input_tokens=100, max_output_tokens=1, max_total_tokens=101)
    with pytest.raises(AppError) as exc:
        run_director(session, run, GOLDEN_GOAL, MockProvider(), max_attempts=1, budget=tiny)
    assert exc.value.code == "director_llm_error"
    assert "预算" in exc.value.message