"""Step 18 测试：Branch 一等公民（创建/复制/切换/比较/废弃/恢复/版本/合并/ending）。"""
import pytest

from app.core.errors import AppError
from app.models import Branch, Project
from app.services.artifacts import persist_versioned_artifact
from app.services.branch import BranchService


def _project(session) -> Project:
    project = Project(goal="制作乙女悬疑Galgame。", template="galgame")
    session.add(project)
    session.commit()
    return project


def _seed_story(session, project_id) -> None:
    story = {
        "graph_id": "g1", "entry_node_id": "n1",
        "variables": [{"name": "affection", "type": "number", "initial": 0, "description": ""}],
        "nodes": [
            {"node_id": "n1", "kind": "scene", "title": "起点", "summary": "", "choices": []},
            {"node_id": "n2", "kind": "ending", "title": "结局", "summary": ""},
        ],
        "edges": [], "metadata": {},
    }
    persist_versioned_artifact(
        session, project_id=project_id, task_id="s4", agent="plot",
        kind="story_graph", content=story, prompt_version="pv:1",
    )
    session.commit()


def _selected(session, project_id) -> Branch:
    return session.query(Branch).filter(Branch.project_id == project_id, Branch.is_selected.is_(True)).first()


def test_create_branch_selected(session_factory):
    session = session_factory()
    project = _project(session)
    branch = BranchService(session).create(project.id, name="主线", state={"affection": 5})
    assert branch.is_selected is True
    assert branch.base_version == 1  # 无 story_graph → 默认 1
    session.close()


def test_switch_single_selected(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A")
    b = BranchService(session).create(project.id, name="B")
    assert _selected(session, project.id).id == b.id  # 新建自动选中
    BranchService(session).switch(project.id, a.id)
    session.expire_all()
    assert _selected(session, project.id).id == a.id
    selected_count = sum(
        1 for x in session.query(Branch).filter(Branch.project_id == project.id).all() if x.is_selected
    )
    assert selected_count == 1
    session.close()


def test_copy_branch(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A", state={"affection": 7})
    clone = BranchService(session).copy(a.id, name="A-副本")
    assert clone.parent_branch_id == a.id
    assert clone.state == {"affection": 7}
    assert clone.id != a.id and clone.is_selected is True
    session.close()


def test_compare_branches(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A", state={"affection": 1}, plan={"tone": "甜"})
    b = BranchService(session).create(project.id, name="B", state={"affection": 9}, plan={"tone": "虐"})
    out = BranchService(session).compare(a.id, b.id)
    assert out["state_diff"]["changed"]["affection"] == {"from": 1, "to": 9}
    assert out["plan_diff"]["changed"]["tone"] == {"from": "甜", "to": "虐"}
    session.close()


def test_abandon_and_restore(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A")
    BranchService(session).abandon(a.id)
    session.expire_all()
    assert session.get(Branch, a.id).status == "abandoned"
    assert session.get(Branch, a.id).is_selected is False
    BranchService(session).restore(a.id)
    session.expire_all()
    assert session.get(Branch, a.id).status == "active"
    session.close()


def test_branch_versions_snapshot(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A")
    BranchService(session).snapshot(a.id, {"nodes": []}, change_reason="v1")
    BranchService(session).snapshot(a.id, {"nodes": ["n1"]}, change_reason="v2")
    versions = BranchService(session).versions(a.id)
    assert [v.version_no for v in versions] == [1, 2]
    assert versions[1].change_reason == "v2"
    session.close()


def test_merge_branches(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A")
    b = BranchService(session).create(project.id, name="B")
    BranchService(session).merge(a.id, b.id)
    session.expire_all()
    assert session.get(Branch, a.id).status == "merged"
    assert _selected(session, project.id).id == b.id
    session.close()


def test_is_ending(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_story(session, project.id)
    ending = BranchService(session).create(project.id, name="结局分支", current_node_id="n2")
    scene = BranchService(session).create(project.id, name="进行中", current_node_id="n1")
    assert BranchService(session).is_ending(ending.id) is True
    assert BranchService(session).is_ending(scene.id) is False
    session.close()


def test_resume_returns_branch_state(session_factory):
    session = session_factory()
    project = _project(session)
    a = BranchService(session).create(project.id, name="A", current_node_id="n1", state={"affection": 3})
    res = BranchService(session).resume(a.id)
    assert res == {"current_node_id": "n1", "state": {"affection": 3}}
    session.close()


def test_branch_not_found(session_factory):
    session = session_factory()
    with pytest.raises(AppError) as e:
        BranchService(session).abandon("no-such-branch")
    assert e.value.code == "branch_not_found"
    session.close()


def test_branch_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    session.close()
    resp = client.post(f"/api/projects/{project.id}/branches", json={"name": "主线"})
    assert resp.status_code == 200, resp.text
    branch = resp.json()
    assert branch["is_selected"] is True
    resp = client.get(f"/api/projects/{project.id}/branches/current")
    assert resp.json()["id"] == branch["id"]