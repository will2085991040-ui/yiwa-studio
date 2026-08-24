"""Step 6 测试：Multi-Agent Orchestrator + WorldAgent（Director -> Orchestrator -> WorldBible Artifact）。"""
import asyncio
import json

import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.world import WORLD_BUDGET, WorldAgent
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.schemas.agent_plan import AgentPlan
from app.schemas.world_bible import WorldBible, world_bible_json_schema
from app.services.prompt_seed import ensure_world_prompt
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


def world_bible_dict() -> dict:
    return {
        "world_id": "world-01", "title": "乙女悬疑娱乐公司", "setting": "娱乐公司内的悬疑恋爱双线",
        "era": "现代", "location": "都市", "rules": ["角色守则", "选择影响走向"],
        "social_structure": "娱乐公司职场与幕后势力",
        "factions": [{"name": "娱乐公司", "description": "主线舞台", "role": "主线场景"}],
        "culture": "粉丝文化", "technology": "当代", "conflicts": ["恋爱与悬疑"],
        "key_locations": [{"name": "公司大楼", "description": "主线发生地"}],
        "world_constraints": ["逻辑自洽"], "consistency_notes": "后续校对",
    }


def _plan_dict() -> dict:
    def t(i, a, o, deps=None):
        return {
            "id": i, "agent_type": a, "objective": o, "dependencies": deps or [],
            "output_schema": {"type": "object"},
        }

    return {
        "goal": GOLDEN_GOAL, "goal_summary": "乙女悬疑互动", "project_type": "galgame",
        "target_audience": "乙女用户", "genre": "乙女悬疑", "tone": "甜宠悬疑",
        "business_objective": "", "creative_objective": "",
        "required_capabilities": ["worldbuilding", "character"],
        "characters_required": "", "worldbuilding_required": "娱乐公司世界观",
        "story_required": "", "scene_required": "", "branch_required": "",
        "dialogue_required": "", "evaluation_required": "",
        "generation_steps": [t("s1", "world", "构建世界观"), t("s2", "character", "角色卡", ["s1"])],
        "success_metrics": [], "constraints": [],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None}, "priority": "high",
    }


@pytest.fixture()
def world_ctx(session_factory):
    session = session_factory()
    ensure_world_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_world(session, run, provider, max_attempts=3):
    plan = AgentPlan.model_validate(_plan_dict())
    task = plan.generation_steps[0]
    return asyncio.run(
        WorldAgent(max_attempts=max_attempts).run({
            "session": session, "run": run, "task": task, "goal": GOLDEN_GOAL, "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "provider": provider,
        })
    )


def test_world_bible_schema_roundtrip():
    schema = world_bible_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)  # 是合法 JSON Schema
    jsonschema.validate(world_bible_dict(), schema)        # 示例数据满足自身 Schema
    bible = WorldBible.model_validate(world_bible_dict())
    assert WorldBible.model_validate_json(bible.model_dump_json()) == bible
    # 结构化而非纯文本：factions / key_locations 是嵌套对象
    assert bible.factions[0].name == "娱乐公司"
    assert bible.key_locations[0].name == "公司大楼"


def test_world_bible_duplicate_faction_names_rejected():
    bad = world_bible_dict()
    bad["factions"] = [{"name": "同党", "description": "a"}, {"name": "同党", "description": "b"}]
    with pytest.raises(ValidationError):
        WorldBible.model_validate(bad)


def test_world_agent_uses_structured_output(world_ctx):
    session, run = world_ctx
    fake = FakeProvider([world_bible_dict()])
    result = _run_world(session, run, fake, max_attempts=1)
    req = fake.captured[0]
    assert req.json_schema["title"] == "WorldBible"        # 走 generate_structured + WorldBible Schema
    assert req.prompt_version == "world_generation:v1"    # PromptVersion 绑定
    assert req.budget == WORLD_BUDGET                        # 预算生效
    assert result["attempts"] == 1
    assert result["artifact"]["kind"] == "world_bible"


def test_world_agent_repairs_invalid_then_succeeds(world_ctx):
    session, run = world_ctx
    bad = world_bible_dict()
    bad["factions"] = [{"name": "同党", "description": "a"}, {"name": "同党", "description": "b"}]  # name 重复
    fake = FakeProvider([bad, world_bible_dict()])
    result = _run_world(session, run, fake, max_attempts=3)
    assert result["attempts"] == 2
    assert result["artifact"]["content"]["world_id"] == "world-01"


def test_orchestrate_golden_scenario(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    pid = created["project_id"]
    resp = client.post(f"/api/orchestrate/{pid}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["key"]: s for s in data["steps"]}
    # 7 步闭环：world/character/relationship/plot/scene/dialogue/finalize 全部真正执行成功
    for key, agent in [
        ("s1", "world"), ("s2", "character"), ("s3", "relationship"),
        ("s4", "plot"), ("s5", "scene"), ("s6", "dialogue"), ("s7", "finalize"),
    ]:
        assert steps[key]["status"] == "succeeded", (key, steps[key])
        assert steps[key]["agent"] == agent
    # 结构 artifact + 收尾 script_book + 节点级 scene:/dialogue: 全量落库
    artifacts = data["artifacts"]
    kinds = {a["kind"] for a in artifacts}
    assert {"world_bible", "character_card:char-01", "relationship_graph", "story_graph", "script_book"} <= kinds
    assert any(k.startswith("scene:") for k in kinds)       # 场景正文已扇出生成
    assert any(k.startswith("dialogue:") for k in kinds)     # 对白已扇出生成
    wb = next(a["content"] for a in artifacts if a["kind"] == "world_bible")
    assert wb["world_id"] == "world-01"
    assert wb["title"] and wb["factions"]
    book = next(a["content"] for a in artifacts if a["kind"] == "script_book")
    assert book["node_count"] >= 1 and "quality" in book
    # GET 回读在一起
    view = client.get(f"/api/orchestrate/{pid}")
    assert view.status_code == 200
    assert view.json()["steps"] == data["steps"]
    assert view.json()["artifacts"] == artifacts


def test_orchestrate_does_not_fake_planned_agents(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    data = client.post(f"/api/orchestrate/{created['project_id']}").json()
    # 7 步闭环全部真正跑通，无 blocked/failed，绝不把未实现 agent 伪装成 succeeded
    assert {s["status"] for s in data["steps"]} == {"succeeded"}
    assert {s["agent"] for s in data["steps"]} == {
        "world", "character", "relationship", "plot", "scene", "dialogue", "finalize",
    }


def test_orchestrate_trace(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    client.post(f"/api/orchestrate/{created['project_id']}")
    traces = client.get(f"/api/projects/{created['project_id']}/traces").json()
    run = next(t for t in traces if t["kind"] == "orchestrate")
    keys = [s["step_key"] for s in run["steps"]]
    step_keys = [
        "task.start", "task.succeeded", "world.input",
        "llm.request", "llm.response", "validation", "artifact",
    ]
    for k in step_keys:
        assert k in keys


def test_orchestrate_without_plan_rejected(client):
    created = client.post("/api/projects", json={"goal": "做一个互动短剧，讲述校园故事"}).json()
    resp = client.post(f"/api/orchestrate/{created['project_id']}")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_agent_plan"