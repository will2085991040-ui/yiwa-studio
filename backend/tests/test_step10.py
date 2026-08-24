"""Step 10 测试：PlotAgent / StoryAgent + StoryGraph 局部操作（延长/分支/锁定）。"""
import asyncio
import copy
import json

import jsonschema
import pytest

from app.agents.plot import PLOT_BUDGET, PlotAgent
from app.core.errors import AppError
from app.llm.provider import MockProvider
from app.llm.types import LLMResponse
from app.models import AgentSpec, Artifact, Project
from app.schemas.agent_plan import AgentPlan
from app.schemas.story_graph import StoryGraph, StoryNode, story_graph_json_schema
from app.services.prompt_seed import ensure_plot_prompt
from app.services.story_ops import add_branch, extend_story
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


def _story_graph() -> dict:
    return {
        "graph_id": "story-01",
        "entry_node_id": "scene_01",
        "variables": [{"name": "affection", "type": "number", "initial": 0, "description": "好感度"}],
        "nodes": [
            {
                "node_id": "scene_01", "kind": "scene", "title": "开局", "content_ref": "scene_01",
                "summary": "女主进入公司",
                "choices": [
                    {
                        "choice_id": "c1", "text": "帮助女主",
                        "effects": [{"variable": "affection", "op": "add", "value": 10}], "next_node": "scene_02",
                    },
                    {"choice_id": "c2", "text": "离开", "next_node": "end_01"},
                ],
            },
            {"node_id": "scene_02", "kind": "scene", "title": "同盟", "content_ref": "scene_02", "summary": "结盟"},
            {"node_id": "end_01", "kind": "ending", "title": "退出", "content_ref": "end_01", "summary": "离开"},
        ],
        "edges": [
            {"edge_id": "e1", "source": "scene_01", "target": "scene_02", "label": "c1"},
            {"edge_id": "e2", "source": "scene_01", "target": "end_01", "label": "c2"},
        ],
        "metadata": {"chapter": 1},
    }


def _plan_dict() -> dict:
    def t(i, a, o, deps=None):
        return {
            "id": i, "agent_type": a, "objective": o,
            "dependencies": deps or [], "output_schema": {"type": "object"},
        }

    return {
        "goal": GOAL, "goal_summary": "乙女悬疑", "project_type": "galgame",
        "target_audience": "乙女用户", "genre": "乙女悬疑", "tone": "甜宠悬疑",
        "business_objective": "", "creative_objective": "",
        "required_capabilities": ["worldbuilding", "character", "relationship", "plot"],
        "characters_required": "三男主一女主", "worldbuilding_required": "娱乐公司",
        "story_required": "5章", "scene_required": "", "branch_required": "",
        "dialogue_required": "", "evaluation_required": "",
        "generation_steps": [
            t("s1", "world", "世界观"), t("s2", "character", "角色卡", ["s1"]),
            t("s3", "relationship", "关系图", ["s1", "s2"]), t("s4", "plot", "剧情图", ["s1", "s2", "s3"]),
        ],
        "success_metrics": [], "constraints": [],
        "budget": {"max_total_tokens": 100000, "max_cost_usd": None}, "priority": "high",
    }


@pytest.fixture()
def plot_ctx(session_factory):
    session = session_factory()
    ensure_plot_prompt(session)
    run = trace_manager.start_run(session, kind="orchestrate")
    yield session, run
    session.close()


def _run_plot(session, run, provider, upstream, revision=None):
    plan = AgentPlan.model_validate(_plan_dict())
    task = plan.generation_steps[3]
    return asyncio.run(
        PlotAgent(max_attempts=3).run({
            "session": session, "run": run, "task": task, "goal": GOAL, "plan": plan,
            "project": {"genre": plan.genre, "tone": plan.tone, "project_type": plan.project_type},
            "upstream": upstream, "provider": provider, "revision": revision,
        })
    )


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
                "graph_id": "rel-01",
                "characters": ["char-01", "char-02"],
                "edges": [{"source_character": "char-01", "target_character": "char-02", "relationship_type": "爱慕"}],
            },
        },
    }


def test_story_graph_schema_lock_field():
    schema = story_graph_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_story_graph(), schema)
    g = StoryGraph.model_validate(_story_graph())
    assert g.metadata == {"chapter": 1}
    assert all(not n.locked for n in g.nodes)  # 默认未锁定
    # locked 字段预留：可表达"该节点后续 Agent 不得修改"
    assert StoryNode(node_id="x", locked=True).locked is True


def test_plot_agent_injects_context(plot_ctx):
    session, run = plot_ctx
    fake = FakeProvider([_story_graph()])
    result = _run_plot(session, run, fake, _upstream())
    req = fake.captured[0]
    assert req.json_schema["title"] == "StoryGraph"
    assert req.prompt_version == "plot_generation:v1"
    assert req.budget == PLOT_BUDGET
    # world + character + relationship 全注入 prompt（World -> Character -> Relationship -> Plot 真实数据流）
    for token in ("乙女悬疑世界", "林晚", "char-01—爱慕→char-02"):
        assert token in req.system
    assert result["artifact"]["kind"] == "story_graph"
    assert result["artifact"]["content"]["graph_id"] == "story-01"
    assert result["attempts"] == 1


def test_plot_agent_repairs_invalid(plot_ctx):
    session, run = plot_ctx
    bad = _story_graph()
    bad["nodes"][1]["node_id"] = "scene_01"  # 重复 node_id -> 拒绝 -> 重试
    fake = FakeProvider([bad, _story_graph()])
    result = _run_plot(session, run, fake, _upstream())
    assert result["attempts"] == 2


def test_golden_story_graph_expresses_interaction(client):
    created = client.post("/api/director/plan", json={"goal": GOAL}).json()
    data = client.post(f"/api/orchestrate/{created['project_id']}").json()
    arts = {a["kind"]: a for a in data["artifacts"]}
    graph = arts["story_graph"]["content"]
    assert graph["graph_id"] == "story-01"
    assert graph["entry_node_id"] == "scene_01"
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"scene", "ending"} <= kinds
    assert graph["variables"]  # Variable
    assert any(c["effects"] for n in graph["nodes"] for c in n.get("choices", []))  # Effect（好感度）
    assert any(c["next_node"] for n in graph["nodes"] for c in n.get("choices", []))  # Branch
    assert graph["edges"]  # 边


def _make_ready(client) -> str:
    created = client.post("/api/director/plan", json={"goal": GOAL}).json()
    assert client.post(f"/api/orchestrate/{created['project_id']}").status_code == 200
    return created["project_id"]


def test_revise_story_graph_creates_v2(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/revise", json={"kind": "story_graph", "instruction": "把结局改得更悬疑"})
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert arts["story_graph"]["version"] == 2
    assert arts["story_graph"]["source"] == "user"
    assert arts["story_graph"]["parent_version"] == 1


def test_extend_story_appends_scenes(client):
    pid = _make_ready(client)
    before = next(a for a in client.get(f"/api/orchestrate/{pid}").json()["artifacts"] if a["kind"] == "story_graph")
    prior_nodes = {n["node_id"] for n in before["content"]["nodes"]}
    resp = client.post(
        f"/api/projects/{pid}/story",
        json={"operation": "extend", "instruction": "再发展三场", "count": 3},
    )
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    graph = arts["story_graph"]["content"]
    # 两个未完结 scene 叶节点（scene_02a/02b）各追加 3 场 -> 6 个新节点
    new_nodes = [n for n in graph["nodes"] if n["node_id"] not in prior_nodes]
    assert len(new_nodes) == 6
    assert arts["story_graph"]["version"] == 2
    assert arts["story_graph"]["source"] == "user"
    assert arts["story_graph"]["change_reason"] == "[extend] 再发展三场"
    # 旧节点仍在，且新节点连边（旧结构不变，新结构追加）
    assert prior_nodes <= {n["node_id"] for n in graph["nodes"]}
    new_ids = {n["node_id"] for n in new_nodes}
    assert any(e["target"] in new_ids for e in graph["edges"])


def test_add_branch_appends_choice_and_scene(client):
    pid = _make_ready(client)
    before = next(a for a in client.get(f"/api/orchestrate/{pid}").json()["artifacts"] if a["kind"] == "story_graph")
    entry = before["content"]["entry_node_id"]
    n_choices = sum(len(n.get("choices", [])) for n in before["content"]["nodes"])
    resp = client.post(
        f"/api/projects/{pid}/story",
        json={"operation": "branch", "instruction": "相信男主", "anchor_node_id": entry},
    )
    assert resp.status_code == 200, resp.text
    graph = {a["kind"]: a for a in resp.json()["artifacts"]}["story_graph"]["content"]
    assert sum(len(n.get("choices", [])) for n in graph["nodes"]) == n_choices + 1
    assert len(graph["nodes"]) == len(before["content"]["nodes"]) + 1
    assert len(graph["edges"]) == len(before["content"]["edges"]) + 1
    # 版本推进 + 用户来源记录
    assert {a["kind"]: a for a in resp.json()["artifacts"]}["story_graph"]["source"] == "user"
    assert {a["kind"]: a for a in resp.json()["artifacts"]}["story_graph"]["version"] == 2


def test_branch_rejects_locked_anchor_and_extend_skips_locked(session_factory):
    """锁定字段预留：add_branch 拒绝锁定锚点；extend 不修改/不延伸锁定叶节点。"""
    session = session_factory()
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.flush()
    session.add(AgentSpec(project_id=project.id, plan=[], policies={}, status="ready"))
    session.flush()
    base = _story_graph()
    base["nodes"][1]["locked"] = True  # scene_02 锁定
    base["nodes"].append({"node_id": "scene_03", "kind": "scene", "locked": False, "summary": "可延长"})
    base["edges"].append({"edge_id": "e3", "source": "scene_01", "target": "scene_03"})
    session.add(Artifact(
        project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
        content=base, prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()

    locked_before = copy.deepcopy(next(n for n in base["nodes"] if n["node_id"] == "scene_02"))

    # add_branch 指向锁定节点 -> 409
    with pytest.raises(AppError) as exc:
        add_branch(session, project.id, instruction="加分支", anchor_node_id="scene_02")
    assert exc.value.code == "locked_node"

    # extend 只延伸未锁定叶节点 scene_03，锁定 scene_02 原样保留且无新出边
    result = extend_story(session, project.id, instruction="延长", count=2)
    graph = next(a["content"] for a in result["artifacts"] if a["kind"] == "story_graph")
    locked_after = next(n for n in graph["nodes"] if n["node_id"] == "scene_02")
    assert locked_after == locked_before
    assert not any(e["source"] == "scene_02" for e in graph["edges"])  # 锁定节点无新出边
    assert len(graph["nodes"]) == len(base["nodes"]) + 2  # 只在 scene_03 后加 2 个
    session.close()