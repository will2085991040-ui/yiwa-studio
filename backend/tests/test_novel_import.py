"""增量：小说导入 → 拆剧本 → 角色卡 → 人物关系 → 串联互动图 测试。"""
from app.services.novel_import import breakdown_novel

_SAMPLE = (
    "第一章 雨夜。\n\n林烬说：这场雨不会停了。\n\n苏晚问：你还在等谁？\n\n"
    "林烬说：等一个不该等的人。\n\n苏晚说：那我陪你一起等。\n\n"
    "两人并肩站在屋檐下，雨声渐密。这是他们相识的第七年，也是谜团浮出的第一夜。"
)


def test_breakdown_novel_shape():
    text = _SAMPLE + "\n\n第二章 真相。" * 6
    bd = breakdown_novel(text, "galgame", "雨夜")
    assert bd["game_type_label"] == "Galgame 恋爱冒险"
    assert bd["scene_count"] >= 1
    assert any(c["name"] in ("林烬", "苏晚") for c in bd["characters"])
    assert bd["relationships"]
    graph = bd["story_graph"]
    assert graph["entry_node_id"]
    assert any(n["kind"] == "ending" for n in graph["nodes"])
    assert any(n["choices"] for n in graph["nodes"] if n["kind"] == "scene")


def test_import_novel_api(client, session_factory):
    resp = client.post("/api/novel/import", json={
        "title": "雨夜第七年",
        "text": _SAMPLE + "\n\n" + "林烬说：真相就在眼前。" * 5,
        "game_type": "galgame",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    pid = body["project_id"]
    assert body["characters"]
    assert body["relationship_count"] >= 1

    chars = client.get(f"/api/projects/{pid}/characters")
    assert chars.status_code == 200
    assert any(c["name"] in ("林烬", "苏晚") for c in chars.json())

    export = client.get(f"/api/projects/{pid}/storygraph/export.html")
    assert export.status_code == 200
    assert "text/html" in export.headers["content-type"]

    check = client.get(f"/api/projects/{pid}/storygraph/check")
    assert check.status_code == 200, check.text
    body = check.json()
    assert body["version"] >= 1
    assert body["ok"] is True
    assert body["errors"] == []