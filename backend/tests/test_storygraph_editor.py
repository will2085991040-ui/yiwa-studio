"""增量 Phase 1：互动剧本节点画布（StoryGraph 编辑器 API）测试。

覆盖：空图读取 / 保存追加版本 / 校验诊断 / 版本历史 / 与 Runtime 试玩闭环。
"""
from app.models import Project


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def _graph() -> dict:
    return {
        "graph_id": "story-test",
        "entry_node_id": "entry",
        "nodes": [
            {
                "node_id": "entry", "kind": "scene", "title": "开场", "summary": "天台相遇",
                "choices": [
                    {"choice_id": "c1", "text": "上前搭话", "effects": [], "next_node": "end_a"},
                    {"choice_id": "c2", "text": "装作没看见", "effects": [], "next_node": "end_b"},
                ],
            },
            {"node_id": "end_a", "kind": "ending", "title": "结局A"},
            {"node_id": "end_b", "kind": "ending", "title": "结局B"},
        ],
        "edges": [],
        "variables": [{"name": "affection", "type": "number", "initial": 0}],
        "metadata": {"endings": 2},
    }


def test_get_empty_graph(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.get(f"/api/projects/{project.id}/storygraph")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["version"] == 0
    assert data["graph"]["nodes"] == []
    assert data["graph"]["entry_node_id"] is None


def test_save_and_read_graph(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.put(
        f"/api/projects/{project.id}/storygraph",
        json={"graph": _graph(), "change_reason": "编辑器首版"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1
    assert resp.json()["graph"]["entry_node_id"] == "entry"

    resp = client.get(f"/api/projects/{project.id}/storygraph")
    data = resp.json()
    assert data["version"] == 1
    assert len(data["graph"]["nodes"]) == 3
    var = data["graph"]["variables"][0]
    assert var["name"] == "affection" and var["type"] == "number" and var["initial"] == 0


def test_save_appends_version(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    client.put(f"/api/projects/{project.id}/storygraph", json={"graph": _graph()})
    g2 = _graph()
    g2["metadata"] = {"endings": 3, "note": "第二版"}
    resp = client.put(f"/api/projects/{project.id}/storygraph", json={"graph": g2})
    assert resp.status_code == 200
    assert resp.json()["version"] == 2

    hist = client.get(f"/api/projects/{project.id}/storygraph/versions")
    assert [v["version"] for v in hist.json()] == [1, 2]


def test_validate_ok(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    resp = client.post(f"/api/projects/{project.id}/storygraph/validate", json={"graph": _graph()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["counts"]["nodes"] == 3 and body["counts"]["endings"] == 2


def test_validate_missing_entry(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    g = _graph()
    g["entry_node_id"] = None
    resp = client.post(f"/api/projects/{project.id}/storygraph/validate", json={"graph": g})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert any("入口" in e for e in resp.json()["errors"])


def test_validate_unreachable_warns(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()

    g = _graph()
    g["nodes"].append({"node_id": "orphan", "kind": "scene", "title": "孤立节点"})
    resp = client.post(f"/api/projects/{project.id}/storygraph/validate", json={"graph": g})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True          # 可达性只是警告，不阻断
    assert any("orphan" in w for w in body["warnings"])
    assert any("死路" in w or "不可达" in w for w in body["warnings"])


def test_editor_graph_playtest_via_runtime(client, session_factory):
    """编辑器保存的图能被 Runtime 直接试玩（闭环验证）。"""
    session = session_factory()
    project = _project(session)
    session.close()

    client.put(f"/api/projects/{project.id}/storygraph", json={"graph": _graph()})
    resp = client.post(f"/api/projects/{project.id}/runtime/sessions")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_node_id"] == "entry"
    assert body["state"]["affection"] == 0

    sid = body["session_id"]
    resp = client.get(f"/api/projects/{project.id}/runtime/sessions/{sid}/choices")
    assert [c["choice_id"] for c in resp.json()] == ["c1", "c2"]

    resp = client.post(
        f"/api/projects/{project.id}/runtime/sessions/{sid}/choice", json={"choice_id": "c1"}
    )
    assert resp.status_code == 200
    assert resp.json()["current_node_id"] == "end_a"


def test_put_unknown_project_404(client):
    resp = client.put("/api/projects/no-such-project/storygraph", json={"graph": _graph()})
    assert resp.status_code == 404


def test_choice_video_timing_round_trip(client, session_factory):
    """互动影视：选项的 video_at_sec（视频第几秒弹出）随图往返持久化（向前兼容）。"""
    session = session_factory()
    project = _project(session)
    session.close()

    g = _graph()
    g["nodes"][0]["choices"][0]["video_at_sec"] = 6.5
    resp = client.put(f"/api/projects/{project.id}/storygraph", json={"graph": g})
    assert resp.status_code == 200, resp.text

    got = client.get(f"/api/projects/{project.id}/storygraph").json()
    c1 = got["graph"]["nodes"][0]["choices"][0]
    assert c1["video_at_sec"] == 6.5


def test_open_player_branch_creates_locked_ai_node(client, session_factory):
    """开放共创分支：玩家写一条走向（story operation=branch）→ 新增 scene 节点+锚点选项；
    再把该节点标 locked=true 保存，确认不可编辑标记持久化。项目经由真实 API 创建（app DB），
    因为 add_branch 需要在应用的 Project 行中找到该项目（与现有纯 storygraph 测试不同）。"""
    # 项目经由 API 创建，保证 Project 行存在于应用所用 DB
    pr = client.post("/api/projects", json={"goal": "测试分支", "template": "galgame"})
    assert pr.status_code == 201, pr.text
    pid = pr.json()["project_id"]

    resp = client.put(f"/api/projects/{pid}/storygraph", json={"graph": _graph()})
    assert resp.status_code == 200, resp.text

    instr = "主角突然觉醒记忆并召唤天界舰队"
    resp = client.post(
        f"/api/projects/{pid}/story",
        json={"operation": "branch", "instruction": instr, "anchor_node_id": "entry"},
    )
    assert resp.status_code == 200, resp.text

    got = client.get(f"/api/projects/{pid}/storygraph").json()["graph"]
    node_ids = {n["node_id"] for n in got["nodes"]}
    assert any(n["title"] == instr and n["kind"] == "scene" for n in got["nodes"])
    # 锚点应新增一个指向该开放分支的选项
    anchor = next(n for n in got["nodes"] if n["node_id"] == "entry")
    assert any(c["next_node"] in node_ids and c["text"] == instr for c in anchor["choices"])

    # 创作者不可编辑：把该分支标为 locked 并保存
    branch = next(n for n in got["nodes"] if n["title"] == instr)
    got_next = client.get(f"/api/projects/{pid}/storygraph").json()["graph"]
    for n in got_next["nodes"]:
        if n["node_id"] == branch["node_id"]:
            n["locked"] = True
    resp2 = client.put(
        f"/api/projects/{pid}/storygraph",
        json={"graph": got_next, "change_reason": "锁定开放分支"},
    )
    assert resp2.status_code == 200, resp2.text
    final = client.get(f"/api/projects/{pid}/storygraph").json()["graph"]
    locked = next(n for n in final["nodes"] if n["node_id"] == branch["node_id"])
    assert locked["locked"] is True