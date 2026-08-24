"""Step 8 测试：Interactive Creation Layer（工作区 / 版本体系 / StoryGraph Schema / 修改与局部执行）。"""
import jsonschema
import pytest
from pydantic import ValidationError

from app.schemas.story_graph import StoryGraph, story_graph_json_schema

GOLDEN_GOAL = (
    "制作一个乙女悬疑Galgame。女主进入一家娱乐公司。三个男主：A顶流演员、B新人导演、"
    "C隐藏身份调查员。包含恋爱线、悬疑线，共5章，3个结局，玩家选择影响好感度和最终结局。"
)


def _make_ready(client) -> str:
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    pid = created["project_id"]
    assert client.post(f"/api/orchestrate/{pid}").status_code == 200
    return pid


# ---------------------------------------------------------------------------
# Story Graph Schema（仅 Schema，无 Runtime）
# ---------------------------------------------------------------------------

def _graph() -> dict:
    def choice(cid, text, value, target):
        return {
            "choice_id": cid, "text": text,
            "effects": [{"variable": "affection", "op": "add", "value": value}],
            "next_node": target,
        }

    return {
        "graph_id": "g-01",
        "nodes": [
            {"node_id": "scene1", "kind": "scene", "title": "开场", "choices": [
                choice("c1", "帮助女主", 10, "scene2"),
                choice("c2", "背叛女主", -20, "scene3"),
            ]},
            {"node_id": "scene2", "kind": "scene", "title": "信任线"},
            {"node_id": "scene3", "kind": "ending", "title": "决裂结局"},
        ],
        "edges": [
            {"edge_id": "e1", "source": "scene1", "target": "scene2", "label": "帮助"},
            {"edge_id": "e2", "source": "scene1", "target": "scene3", "label": "背叛"},
        ],
        "variables": [{"name": "affection", "type": "number", "initial": 0}],
        "entry_node_id": "scene1",
    }


def test_story_graph_schema_roundtrip():
    schema = story_graph_json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_graph(), schema)
    g = StoryGraph.model_validate(_graph())
    assert StoryGraph.model_validate_json(g.model_dump_json()) == g
    assert g.nodes[0].choices[0].effects[0].variable == "affection"


def test_story_graph_duplicate_node_rejected():
    bad = _graph()
    bad["nodes"].append({"node_id": "scene1", "kind": "scene", "title": "重复"})
    with pytest.raises(ValidationError):
        StoryGraph.model_validate(bad)


def test_story_graph_choice_next_missing_rejected():
    bad = _graph()
    bad["nodes"][0]["choices"][0]["next_node"] = "ghost"
    with pytest.raises(ValidationError):
        StoryGraph.model_validate(bad)


def test_story_graph_duplicate_variable_rejected():
    bad = _graph()
    bad["variables"].append({"name": "affection", "type": "number", "initial": 1})
    with pytest.raises(ValidationError):
        StoryGraph.model_validate(bad)


# ---------------------------------------------------------------------------
# 版本体系 + 用户修改 + 局部执行
# ---------------------------------------------------------------------------

def test_project_has_workspace_fields(client):
    created = client.post("/api/director/plan", json={"goal": GOLDEN_GOAL}).json()
    projects = client.get("/api/projects").json()
    p = next(x for x in projects if x["id"] == created["project_id"])
    assert p["title"]
    assert p["current_version"] == 1


def test_revise_character_creates_v2(client):
    pid = _make_ready(client)
    resp = client.post(
        f"/api/projects/{pid}/revise",
        json={"kind": "character_card:char-01", "instruction": "让女主更加傲娇"},
    )
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert {"world_bible", "character_card:char-01", "relationship_graph", "story_graph"} <= set(arts)
    # world 未动；character_card:char-01 升 v2（用户修改，父版本=v1）
    assert arts["world_bible"]["version"] == 1 and arts["world_bible"]["is_latest"] is True
    cc = arts["character_card:char-01"]
    assert cc["version"] == 2 and cc["is_latest"] is True
    assert cc["source"] == "user"
    assert cc["parent_version"] == 1
    assert cc["change_reason"] == "让女主更加傲娇"
    # 历史：character_card:char-01 有 v1+v2，旧版本 is_latest=False，world 保持 v1
    history = client.get(f"/api/projects/{pid}/artifacts").json()
    cc_hist = [a for a in history if a["kind"] == "character_card:char-01"]
    assert [a["version"] for a in cc_hist] == [1, 2]
    assert next(a for a in cc_hist if a["version"] == 1)["is_latest"] is False
    wb_hist = [a for a in history if a["kind"] == "world_bible"]
    assert [a["version"] for a in wb_hist] == [1]
    # 项目整体版本随之递增
    projects = client.get("/api/projects").json()
    assert next(x for x in projects if x["id"] == pid)["current_version"] == 2


def test_revise_world_creates_v2(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/revise", json={"kind": "world_bible", "instruction": "加入克苏鲁元素"})
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    assert arts["world_bible"]["version"] == 2
    assert arts["world_bible"]["source"] == "user"
    assert arts["character_card:char-01"]["version"] == 1  # character 未受影响


def test_rerun_task_creates_v2(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/tasks/s2/run")
    assert resp.status_code == 200, resp.text
    arts = {a["kind"]: a for a in resp.json()["artifacts"]}
    cc = arts["character_card:char-01"]
    assert cc["version"] == 2
    assert cc["source"] == "agent"
    assert cc["parent_version"] == 1
    assert cc["is_latest"] is True


def test_rerun_on_demand_agent_rejected(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/tasks/s6/run")  # s6 = dialogue（on-demand，非流水线单任务）
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "on_demand_agent"


def test_rerun_finalize_rejected(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/tasks/s7/run")  # s7 = finalize（确定性收尾）
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "not_rerunnable"


def test_revise_unknown_kind_rejected(client):
    pid = _make_ready(client)
    resp = client.post(f"/api/projects/{pid}/revise", json={"kind": "scene_content", "instruction": "改场景"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_kind"


def test_revise_requires_agent_plan(client):
    created = client.post("/api/projects", json={"goal": "做一个互动短剧，讲述校园故事"}).json()
    resp = client.post(
        f"/api/projects/{created['project_id']}/revise",
        json={"kind": "character_card", "instruction": "x"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "no_agent_plan"