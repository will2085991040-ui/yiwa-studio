"""增量：互动影视 HTML 导出 · 干净移植测试。"""
from app.models import Artifact, Project
from app.services.if_export import build_playable_html


def _story() -> dict:
    return {
        "graph_id": "story-export", "entry_node_id": "start",
        "variables": [{"name": "affection", "type": "number", "initial": 0, "description": "好感"}],
        "nodes": [
            {
                "node_id": "start", "kind": "scene", "title": "开头", "summary": "你走进房间",
                "choices": [
                    {"choice_id": "c1", "text": "问好", "condition": None, "effects": [], "next_node": "end_good"},
                ],
            },
            {"node_id": "end_good", "kind": "ending", "title": "好结局", "summary": ""},
        ],
        "edges": [], "metadata": {},
    }


def _seed(session) -> Project:
    project = Project(goal="导出测试", template="interactive_film")
    session.add(project)
    session.flush()
    session.add(
        Artifact(project_id=project.id, task_id="s4", agent="plot", kind="story_graph",
                 content=_story(), prompt_version="pv:1", version=1, is_latest=True)
    )
    session.commit()
    return project


def test_build_playable_html_contains_graph_and_player():
    html = build_playable_html(_story())
    assert "<!doctype html>" in html
    assert "var GRAPH=" in html
    assert "if-player" in html
    assert "entry_node_id" in html  # 图 JSON 已内嵌
    assert "重新开始" in html


def test_build_playable_html_escapes_script_breakout():
    graph = _story()
    graph["nodes"][0]["summary"] = "</script><script>alert(1)</script>"
    html = build_playable_html(graph)
    assert "</script><script>alert(1)</script>" not in html
    assert "\\u003c/script>" in html  # `<` 被转义成 JSON 转义


def test_export_uses_typed_ending():
    graph = _story()
    graph["endings"] = [{"ending_id": "e1", "node_id": "end_good", "title": "圆满", "type": "good"}]
    html = build_playable_html(graph)
    assert "好结局" in html


def test_export_endpoint(client, session_factory):
    session = session_factory()
    project = _seed(session)
    session.close()

    resp = client.get(f"/api/projects/{project.id}/storygraph/export.html")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/html")
    assert "var GRAPH=" in resp.text


def test_export_endpoint_400_without_graph(client, session_factory):
    session = session_factory()
    project = Project(goal="空项目", template="galgame")
    session.add(project)
    session.commit()
    session.close()

    resp = client.get(f"/api/projects/{project.id}/storygraph/export.html")
    assert resp.status_code == 400