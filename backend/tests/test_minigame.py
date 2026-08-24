"""增量 Phase 4：小游戏节点 + postMessage 结果协议测试。"""
from app.models import Artifact, Project
from app.schemas.minigame import RESULT_STATE_KEY, SCORE_STATE_KEY
from app.schemas.story_graph import StoryGraph


def _story() -> dict:
    return {
        "graph_id": "mg-1", "entry_node_id": "game",
        "variables": [{"name": "score", "type": "number", "initial": 0, "description": "得分"}],
        "nodes": [
            {
                "node_id": "game", "kind": "minigame", "title": "连点小游戏",
                "minigame": {
                    "game_id": "click", "title": "连点",
                    "success_result": "success", "score_variable": "score",
                },
                "choices": [
                    {"choice_id": "c_p", "text": "完美线",
                     "condition": "_last_minigame == 'perfect'", "effects": [], "next_node": "perfect_end"},
                    {"choice_id": "c_s", "text": "成功线",
                     "condition": "_last_minigame == 'success'", "effects": [], "next_node": "success_end"},
                ],
            },
            {"node_id": "perfect_end", "kind": "ending", "title": "完美结局", "summary": ""},
            {"node_id": "success_end", "kind": "ending", "title": "成功结局", "summary": ""},
        ],
        "edges": [], "metadata": {},
    }


def _seed(session, story) -> Project:
    project = Project(goal="小游戏互动测试", template="galgame")
    session.add(project)
    session.flush()
    session.add(
        Artifact(project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
                 content=story, prompt_version="pv:1", version=1, is_latest=True)
    )
    session.commit()
    return project


def test_protocol_endpoint(client):
    resp = client.get("/api/meta/minigame-protocol")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_type"] == "funloom:minigame:complete"
    assert body["results"] == ["success", "perfect"]


def test_story_graph_accepts_minigame_kind():
    g = StoryGraph.model_validate(_story())
    game = next(n for n in g.nodes if n.kind == "minigame")
    assert game.minigame is not None
    assert game.minigame.game_id == "click"
    assert game.minigame.success_result == "success"
    assert game.minigame.score_variable == "score"


def test_minigame_result_records_state_and_branches(client, session_factory):
    session = session_factory()
    project = _seed(session, _story())
    session.close()

    sid = client.post(f"/api/projects/{project.id}/runtime/sessions").json()["session_id"]
    resp = client.post(
        f"/api/projects/{project.id}/runtime/sessions/{sid}/minigame-result",
        json={"game_id": "click", "result": "perfect", "score": 120},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["last_result"] == "perfect"
    assert body["session"]["state"][RESULT_STATE_KEY] == "perfect"
    assert body["session"]["state"][SCORE_STATE_KEY] == 120
    assert body["session"]["state"]["score"] == 120  # score_variable 已写入
    choice_ids = [c["choice_id"] for c in body["choices"]]
    assert "c_p" in choice_ids and "c_s" not in choice_ids  # 条件分支：perfect 只出完美线


def test_minigame_result_rejects_non_minigame_node(client, session_factory):
    story = _story()
    story["nodes"][0]["kind"] = "scene"
    story["nodes"][0]["minigame"] = None
    session = session_factory()
    project = _seed(session, story)
    session.close()

    sid = client.post(f"/api/projects/{project.id}/runtime/sessions").json()["session_id"]
    resp = client.post(
        f"/api/projects/{project.id}/runtime/sessions/{sid}/minigame-result",
        json={"result": "success"},
    )
    assert resp.status_code == 422


def test_minigame_result_invalid_result_422(client, session_factory):
    session = session_factory()
    project = _seed(session, _story())
    session.close()

    sid = client.post(f"/api/projects/{project.id}/runtime/sessions").json()["session_id"]
    resp = client.post(
        f"/api/projects/{project.id}/runtime/sessions/{sid}/minigame-result",
        json={"result": "foobar"},
    )
    assert resp.status_code == 422