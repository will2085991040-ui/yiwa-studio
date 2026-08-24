"""Step 18 附加：Branch API 全生命周期覆盖（HTTP 面）。"""
from app.models import Project
from app.services.artifacts import persist_versioned_artifact


def _project(client, session_factory) -> str:
    session = session_factory()
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    pid = project.id
    story = {
        "graph_id": "g1", "entry_node_id": "n1",
        "variables": [], "edges": [], "metadata": {},
        "nodes": [
            {"node_id": "n1", "kind": "scene", "title": "起点", "summary": "", "choices": []},
            {"node_id": "n2", "kind": "ending", "title": "结局", "summary": ""},
        ],
    }
    persist_versioned_artifact(
        session, project_id=pid, task_id="s1", agent="plot",
        kind="story_graph", content=story, prompt_version="pv:1",
    )
    session.commit()
    session.close()
    return pid


def test_branch_api_full_lifecycle(client, session_factory):
    pid = _project(client, session_factory)
    base = f"/api/projects/{pid}"
    a = client.post(f"{base}/branches", json={"name": "A", "state": {"affection": 1}}).json()
    b = client.post(f"{base}/branches", json={"name": "B", "state": {"affection": 9}}).json()
    assert b["is_selected"] is True
    assert client.get(f"{base}/branches/current").json()["id"] == b["id"]

    assert len(client.get(f"{base}/branches").json()) == 2
    cmp = client.post(f"{base}/branches/compare", json={"branch_a_id": a["id"], "branch_b_id": b["id"]}).json()
    assert cmp["state_diff"]["changed"]["affection"] == {"from": 1, "to": 9}

    assert client.post(f"{base}/branches/{a['id']}/switch").json()["is_selected"] is True
    clone = client.post(f"{base}/branches/{a['id']}/copy").json()
    assert clone["parent_branch_id"] == a["id"]

    client.post(f"{base}/branches/{a['id']}/snapshot", json={"content": {"nodes": []}, "change_reason": "v1"})
    versions = client.get(f"{base}/branches/{a['id']}/versions").json()
    assert [v["version_no"] for v in versions] == [1]

    assert client.post(f"{base}/branches/{a['id']}/abandon").json()["status"] == "abandoned"
    assert client.post(f"{base}/branches/{a['id']}/restore").json()["status"] == "active"

    end = client.post(f"{base}/branches", json={"name": "End", "current_node_id": "n2"}).json()
    assert client.get(f"{base}/branches/{end['id']}/ending").json()["is_ending"] is True

    merged = client.post(f"{base}/branches/{a['id']}/merge", json={"target_branch_id": b["id"]}).json()
    assert merged["status"] == "merged"