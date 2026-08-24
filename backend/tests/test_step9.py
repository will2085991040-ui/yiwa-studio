"""Step 9 测试：RelationshipAgent Vertical Slice（World -> Character -> Relationship -> RelationshipGraph）。"""
import asyncio
import json

import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.relationship import RELATIONSHIP_BUDGET, RelationshipAgent
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.schemas.agent_plan import AgentPlan
from app.schemas.relationship_graph import RelationshipGraph, relationship_graph_json_schema
from app.services.prompt_seed import ensure_relationship_prompt
from app.trace.manager import trace_manager

GOLDEN_GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


class FakeProvider(MockProvider):
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


def _card(cid, name, role):
    return {"character_id": cid, "name": name, "role": role}


def _upstream() -> dict:
    """task_id 键化的上游：1 个 WorldBible + 3 张 CharacterCard。"""
    return {
        "s1": {
            "kind": "world_bible",
            "content": {"world_id": "world-01", "title": "乙女悬疑世界", "setting": "娱乐公司悬疑"},
        },
        "c1": {"kind": "character_card", "content": _card("char-01", "林晚", "女主")},
        "c2": {"kind": "character_card", "content": _card("char-02", "顾言", "男主A·顶流演员")},
        "c3": {"kind": "character_card", "content": _card("char-03", "陆沉", "隐藏调查员")},
    }


def _graph() -> dict:
    def change(trigger, var, value, branch):
        return {
            "trigger": trigger,
            "effects": [{"variable": var, "op": "add", "value": value}],
            "resulting_branch": branch,
        }

    return {
        "graph_id": "rel-01",
        "characters": ["char-01", "char-02", "char-03"],
        "edges": [
            {
                "edge_id": "e1", "source_character": "char-01", "target_character": "char-02",
                "relationship_type": "爱慕", "affection": 30, "trust": 50, "hostility": 0,
                "secrets": ["男主A隐藏调查背景"], "rules": ["试探中靠近"], "triggers": ["公司危机"],
                "possible_changes": [
                    change("玩家帮助男主A", "affection", 10, "scene_05a"),
                    change("玩家欺骗男主A", "trust", -30, "scene_05b"),
                ],
                "relationship_arc": ["初识", "试探", "同盟"],
            },
            {
                "edge_id": "e2", "source_character": "char-01", "target_character": "char-03",
                "relationship_type": "怀疑", "affection": 0, "trust": 10, "hostility": 40,
            },
        ],
    }


def _plan_dict() -> dict:
    def t(i, a, o, deps=None):
        return {
            "id": i, "agent_type": a, "objective": o,
            "dependencies": deps or [], "output_schema": {"type": "object"},
        }

    return {
        "goal": GOLDEN_GOAL, "goal_summary": "乙女悬疑", "project_type": "galgame",
        "target_audience": "乙女用户", "genre": "乙女悬疑", "tone": "甜宠悬疑",
        "business_objective": "", "creative_objective": "",
        "required_capabilities": ["worldbuilding", "character", "relationship"],
        "characters_required": "三男主一女主", "worldbuilding_required": "娱乐公司",
        "story_required": "", "scene_required": "", "branch_required": "",
        "dialogue_required": "", "evaluation_required": "",
        "generation_steps": [
            t("s1", "world", "构建世界观"),
            t("s2", "character", "角色卡", ["s1"]),
            t("s3", "relationship", "关系图", ["s1", "s2"]),
        ],
        "success_metrics": [], "constraints": [],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None}, "priority": "high",
    }


@pytest.fixture()
def rel_ctx(session_factory):
    session = session_factory()
    ensure_relationship_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_relationship(session, run, provider, upstream, max_attempts=3):
    plan = AgentPlan.model_validate(_plan_dict())
    task = plan.generation_steps[2]
    return asyncio.run(
        RelationshipAgent(max_attempts=max_attempts).run({
            "session": session, "run": run, "task": task, "goal": GOLDEN_GOAL, "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "provider": provider,
        })
    )


def test_relationship_graph_schema_roundtrip():
    schema = relationship_graph_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_graph(), schema)
    g = RelationshipGraph.model_validate(_graph())
    assert RelationshipGraph.model_validate_json(g.model_dump_json()) == g
    # 关系变化复用 StoryEffect，满足「玩家选择 -> 效果 -> 新状态 -> 分支」
    assert g.edges[0].possible_changes[0].effects[0].variable == "affection"


def test_relationship_graph_self_edge_rejected():
    bad = _graph()
    bad["edges"].append({
        "edge_id": "e3", "source_character": "char-01",
        "target_character": "char-01", "relationship_type": "自恋",
    })
    with pytest.raises(ValidationError):
        RelationshipGraph.model_validate(bad)


def test_relationship_agent_injects_characters_and_world(rel_ctx):
    session, run = rel_ctx
    fake = FakeProvider([_graph()])
    result = _run_relationship(session, run, fake, _upstream())
    req = fake.captured[0]
    assert req.json_schema["title"] == "RelationshipGraph"
    assert req.prompt_version == "relationship_generation:v1"
    assert req.budget == RELATIONSHIP_BUDGET
    # 上游多张 CharacterCard + WorldBible 被注入 prompt（task_id 键化读取）
    for name in ("林晚", "顾言", "陆沉", "乙女悬疑世界"):
        assert name in req.system
    assert result["artifact"]["kind"] == "relationship_graph"
    assert result["artifact"]["content"]["graph_id"] == "rel-01"
    assert result["attempts"] == 1


def test_relationship_agent_repairs_invalid(rel_ctx):
    session, run = rel_ctx
    bad = _graph()
    bad["edges"][0]["edge_id"] = "e2"  # 与 e2 重复 -> Pydantic 拒绝 -> 重试
    fake = FakeProvider([bad, _graph()])
    result = _run_relationship(session, run, fake, _upstream(), max_attempts=3)
    assert result["attempts"] == 2
    assert result["artifact"]["content"]["graph_id"] == "rel-01"


def test_orchestrate_golden_scenario_relationship(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    resp = client.post(f"/api/orchestrate/{created['project_id']}")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    steps = {s["key"]: s for s in data["steps"]}
    assert steps["s1"]["status"] == "succeeded" and steps["s1"]["agent"] == "world"
    assert steps["s2"]["status"] == "succeeded" and steps["s2"]["agent"] == "character"
    assert steps["s3"]["status"] == "succeeded" and steps["s3"]["agent"] == "relationship"
    assert steps["s4"]["status"] == "succeeded" and steps["s4"]["agent"] == "plot"
    assert steps["s5"]["status"] == "succeeded" and steps["s5"]["agent"] == "scene"
    artifacts = {a["kind"]: a for a in data["artifacts"]}
    core = {"world_bible", "character_card:char-01", "relationship_graph", "story_graph", "script_book"}
    assert core <= set(artifacts)
    graph = artifacts["relationship_graph"]["content"]
    assert graph["graph_id"] == "rel-01"
    assert graph["characters"] == ["char-01"]


def test_rerun_relationship_creates_v2(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    pid = created["project_id"]
    client.post(f"/api/orchestrate/{pid}")
    resp = client.post(f"/api/projects/{pid}/tasks/s3/run")
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert arts["relationship_graph"]["version"] == 2
    assert arts["relationship_graph"]["source"] == "agent"
    assert arts["relationship_graph"]["parent_version"] == 1


def test_revise_relationship_creates_v2(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    pid = created["project_id"]
    client.post(f"/api/orchestrate/{pid}")
    resp = client.post(
        f"/api/projects/{pid}/revise",
        json={"kind": "relationship_graph", "instruction": "增加女主与反派的对立关系"},
    )
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert arts["relationship_graph"]["version"] == 2
    assert arts["relationship_graph"]["source"] == "user"
    assert arts["relationship_graph"]["change_reason"] == "增加女主与反派的对立关系"