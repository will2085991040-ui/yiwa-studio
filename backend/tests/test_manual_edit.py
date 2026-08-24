"""手动编辑已生成内容（Step 22）：source=user 覆盖任意 versioned Artifact，schema 校验 + scene_id 引用。"""
from app.models import Artifact


def _create(client, goal="制作一个宏大世界观"):
    return client.post("/api/projects", json={"goal": goal}).json()["project_id"]


def _seed_world(session, pid) -> None:
    session.add(Artifact(
        project_id=pid, task_id="s1", agent="world", kind="world_bible",
        content={"world_id": "w1", "title": "旧世界", "setting": "蒸汽朋克都市"},
        prompt_version="world_generation:v1", version=1, is_latest=True,
    ))
    session.commit()


def test_manual_edit_world_bible_creates_v2(client, session_factory):
    pid = _create(client)
    session = session_factory()
    _seed_world(session, pid)
    session.close()

    r = client.put(f"/api/projects/{pid}/artifacts/content", json={
        "kind": "world_bible",
        "content": {"world_id": "w1", "title": "新世界", "setting": "废土都市",
                    "era": "2120", "rules": ["铁律一"], "factions": [{"name": "议会"}]},
        "change_reason": "手动把标题改为新世界",
    })
    assert r.status_code == 200, r.text
    arts = {a["kind"]: a for a in r.json()["artifacts"]}
    wb = arts["world_bible"]
    assert wb["version"] == 2
    assert wb["source"] == "user"
    assert wb["content"]["title"] == "新世界"
    assert wb["content"]["era"] == "2120"


def test_manual_edit_rejects_invalid_schema(client, session_factory):
    pid = _create(client)
    session = session_factory()
    _seed_world(session, pid)
    session.close()

    r = client.put(f"/api/projects/{pid}/artifacts/content", json={
        "kind": "world_bible",
        "content": {"world_id": "w1"},  # 缺 title / setting
    })
    assert r.status_code == 422


def test_manual_edit_scene_forces_scene_id(client, session_factory):
    pid = _create(client, goal="做一个互动短剧")
    session = session_factory()
    session.add(Artifact(
        project_id=pid, task_id="s4", agent="plot", kind="story_graph",
        content={"nodes": [{"node_id": "n1", "title": "天台"}], "edges": [], "variables": []},
        prompt_version="plot_generation:v1", version=1, is_latest=True,
    ))
    session.commit()
    session.close()

    r = client.put(f"/api/projects/{pid}/artifacts/content", json={
        "kind": "scene:n1",
        "content": {"synopsis": "雨夜天台的第一次对峙", "summary": "对峙"},
        "change_reason": "手动改场景",
    })
    assert r.status_code == 200, r.text
    arts = {a["kind"]: a for a in r.json()["artifacts"]}
    scene = arts["scene:n1"]
    assert scene["version"] == 1
    assert scene["source"] == "user"
    assert scene["content"]["scene_id"] == "n1"