"""Step 11 测试：SceneAgent Vertical Slice（按节点局部生成/修改/扩写场景）。"""
import asyncio
import json

import jsonschema
import pytest
from pydantic import ValidationError

from app.agents.scene import SCENE_BUDGET, SceneAgent
from app.core.errors import AppError
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan, ProductionTask
from app.schemas.scene import SceneContent, scene_json_schema
from app.services.prompt_seed import ensure_scene_prompt
from app.services.scene_service import run_scene_operation
from app.trace.manager import trace_manager

GOAL = (
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


def _scene() -> dict:
    return {
        "scene_id": "scene_01", "title": "入职第一天", "summary": "女主初入公司",
        "location": "前台大厅", "time": "上午", "atmosphere": "紧张",
        "characters_present": ["char-01"],
        "events": ["办理入职", "遇见调查员"],
        "visual_direction": "冷色调", "camera_direction": "中景", "stage_direction": "入场",
        "emotional_beats": ["忐忑", "好奇"],
        "state_changes": [{"variable": "affection", "op": "add", "value": 0}],
        "continuity_notes": "铺垫男主A",
        "asset_requirements": {},
    }


def _story() -> dict:
    return {
        "graph_id": "story-01", "entry_node_id": "scene_01",
        "variables": [{"name": "affection", "type": "number", "initial": 0, "description": "好感度"}],
        "nodes": [
            {
                "node_id": "scene_01", "kind": "scene", "title": "开局", "summary": "女主进入公司",
                "choices": [
                    {
                        "choice_id": "c1", "text": "帮助女主",
                        "effects": [{"variable": "affection", "op": "add", "value": 10}],
                        "next_node": "scene_02a",
                    },
                    {"choice_id": "c2", "text": "离开", "next_node": "end_01"},
                ],
            },
            {"node_id": "scene_02a", "kind": "scene", "title": "同盟", "summary": "结盟"},
            {"node_id": "end_01", "kind": "ending", "title": "退出", "summary": "离开"},
        ],
        "edges": [
            {"edge_id": "e1", "source": "scene_01", "target": "scene_02a", "label": "c1"},
            {"edge_id": "e2", "source": "scene_01", "target": "end_01", "label": "c2"},
        ],
        "metadata": {},
    }


def _upstream() -> dict:
    return {
        "s1": {
            "kind": "world_bible",
            "content": {"world_id": "world-01", "title": "乙女悬疑世界", "setting": "娱乐公司"},
        },
        "s2": {"kind": "character_card", "content": {"character_id": "char-01", "name": "林晚", "role": "女主"}},
        "s3": {
            "kind": "relationship_graph",
            "content": {
                "graph_id": "rel-01", "characters": ["char-01", "char-02"],
                "edges": [{"source_character": "char-01", "target_character": "char-02", "relationship_type": "爱慕"}],
            },
        },
        "s4": {"kind": "story_graph", "content": _story()},
    }


@pytest.fixture()
def scene_ctx(session_factory):
    session = session_factory()
    ensure_scene_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_scene(session, run, provider, upstream, node_id, revision=None):
    task = ProductionTask(id=f"scene-{node_id}", agent_type="scene", objective="生成该场景内容")
    return asyncio.run(
        SceneAgent(max_attempts=3).run({
            "session": session, "run": run, "task": task, "goal": GOAL,
            "node_id": node_id, "upstream": upstream, "provider": provider, "revision": revision,
        })
    )


def test_scene_schema_roundtrip():
    schema = scene_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_scene(), schema)
    s = SceneContent.model_validate(_scene())
    assert SceneContent.model_validate_json(s.model_dump_json()) == s
    assert s.scene_id == "scene_01"
    assert s.asset_requirements == {}


def test_scene_schema_rejects_invalid():
    bad = _scene()
    bad["events"] = ["办理入职", ""]  # 空字符串
    with pytest.raises(ValidationError):
        SceneContent.model_validate(bad)
    bad2 = _scene()
    bad2["characters_present"] = ["char-01", "char-01"]  # 重复
    with pytest.raises(ValidationError):
        SceneContent.model_validate(bad2)
    bad3 = _scene()
    bad3["scene_id"] = "scene 01"  # 含空格
    with pytest.raises(ValidationError):
        SceneContent.model_validate(bad3)


def test_scene_agent_injects_context(scene_ctx):
    session, run = scene_ctx
    fake = FakeProvider([_scene()])
    result = _run_scene(session, run, fake, _upstream(), "scene_01")
    req = fake.captured[0]
    assert req.json_schema["title"] == "SceneContent"
    assert req.prompt_version == "scene_generation:v1"
    assert req.budget == SCENE_BUDGET
    # world + character + relationship + story graph + 节点前后关系/选择/变量 全注入
    for token in ("乙女悬疑世界", "林晚", "爱慕", "scene_01", "scene_02a", "帮助女主", "affection"):
        assert token in req.system
    assert result["artifact"]["kind"] == "scene"
    assert result["artifact"]["content"]["scene_id"] == "scene_01"  # 稳定引用被强制
    assert result["attempts"] == 1


def test_scene_agent_node_not_found(scene_ctx):
    session, run = scene_ctx
    with pytest.raises(AppError) as exc:
        _run_scene(session, run, FakeProvider([_scene()]), _upstream(), "scene_99")
    assert exc.value.code == "node_not_found"


def _make_ready(client) -> str:
    created = client.post("/api/director/plan", json={"goal": GOAL}).json()
    assert client.post(f"/api/orchestrate/{created['project_id']}").status_code == 200
    return created["project_id"]


def test_generate_scene_is_local_and_persisted(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/scene", json={"operation": "generate", "node_id": "scene_01"})
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert "scene:scene_01" in arts
    scene = arts["scene:scene_01"]
    assert scene["content"]["scene_id"] == "scene_01"
    # 一键生成已扇出场景 v1，故此处局部生成得到 v2
    assert scene["version"] == 2 and scene["source"] == "agent"
    # 局部生成：world/character/relationship/story_graph 版本均未变（不重新生成整个项目）
    for k in ("world_bible", "character_card:char-01", "relationship_graph", "story_graph"):
        assert arts[k]["version"] == 1


def test_revise_scene_creates_v2(client):
    pid = _make_ready(client)
    client.post(f"/api/projects/{pid}/scene", json={"operation": "generate", "node_id": "scene_01"})
    resp = client.post(
        f"/api/projects/{pid}/scene",
        json={"operation": "revise", "node_id": "scene_01", "instruction": "把这一场改成暧昧的雨夜"},
    )
    assert resp.status_code == 200, resp.text
    scene = {a["kind"]: a for a in resp.json()["artifacts"]}["scene:scene_01"]
    # 扇出 v1 -> 局部生成 v2 -> 修改 v3
    assert scene["version"] == 3 and scene["source"] == "user"
    assert scene["parent_version"] == 2 and scene["change_reason"] == "把这一场改成暧昧的雨夜"


def test_expand_scene_appends_event_beat(client):
    pid = _make_ready(client)
    client.post(f"/api/projects/{pid}/scene", json={"operation": "generate", "node_id": "scene_02a"})
    resp = client.post(
        f"/api/projects/{pid}/scene",
        json={"operation": "expand", "node_id": "scene_02a", "instruction": "再延长两幕"},
    )
    assert resp.status_code == 200, resp.text
    scene = {a["kind"]: a for a in resp.json()["artifacts"]}["scene:scene_02a"]
    assert scene["version"] == 3  # 扇出 v1 -> 生成 v2 -> 扩写 v3
    assert scene["change_reason"] == "[expand] 再延长两幕"
    assert any("再延长两幕" in e for e in scene["content"]["events"])


def test_two_scenes_version_independently(client):
    pid = _make_ready(client)
    client.post(f"/api/projects/{pid}/scene", json={"operation": "generate", "node_id": "scene_01"})
    out = client.post(f"/api/projects/{pid}/scene", json={"operation": "generate", "node_id": "scene_02a"}).json()
    arts = {a["kind"]: a for a in out["artifacts"]}
    assert arts["scene:scene_01"]["version"] == 2  # 各自独立版本链（扇出 v1 后各自生成 v2）
    assert arts["scene:scene_02a"]["version"] == 2


def test_locked_scene_rejected(session_factory):
    """locked SceneNode 被拒绝生成/修改（409 → AppError.code=locked_node）。"""
    session = session_factory()
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.flush()
    plan = AgentPlan.model_validate({
        "goal": GOAL, "goal_summary": "测试", "project_type": "galgame",
        "target_audience": "乙女", "genre": "乙女悬疑", "tone": "甜宠",
        "generation_steps": [{"id": "s4", "agent_type": "plot", "objective": "剧情图"}],
    })
    session.add(AgentSpec(project_id=project.id, policies={"agent_plan": plan.model_dump()}, plan=[], status="ready"))
    session.flush()
    story = {
        "graph_id": "story-lock", "entry_node_id": "scene_01",
        "nodes": [{"node_id": "scene_01", "kind": "scene", "locked": True, "summary": "锁定场景"}],
        "edges": [], "variables": [], "metadata": {},
    }
    session.add(Artifact(
        project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
        content=story, prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()

    with pytest.raises(AppError) as exc:
        asyncio.run(run_scene_operation(session, project.id, operation="generate", node_id="scene_01"))
    assert exc.value.code == "locked_node"
    session.close()