"""Step 16 测试：Creative Action 生命周期 + HITL（风险分级 / 锁定治理 / 提议确认）。"""
import pytest

from app.core.errors import AppError
from app.models import ActionProposal, Artifact, PlayerSession, Project
from app.services.actions import ActionExecution, CreativeAction
from app.services.artifacts import persist_versioned_artifact

GOAL = "制作一个乙女悬疑Galgame。"


def _project(session) -> Project:
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.commit()
    return project


def _seed_versions(session, project_id) -> None:
    for content in ({"title": "v1"}, {"title": "v2"}, {"title": "v3"}):
        persist_versioned_artifact(
            session, project_id=project_id, task_id="s4", agent="plot",
            kind="story_graph", content=content, prompt_version="pv:1",
        )
        session.commit()


def _seed_locked(session, project_id) -> None:
    story = {
        "entry_node_id": "n1",
        "variables": [],
        "nodes": [{"node_id": "n1", "kind": "scene", "title": "t", "summary": "", "locked": True, "choices": []}],
        "edges": [], "metadata": {},
    }
    persist_versioned_artifact(
        session, project_id=project_id, task_id="s4", agent="plot",
        kind="story_graph", content=story, prompt_version="pv:1",
    )
    session.commit()


def _count(session, project_id) -> int:
    return session.query(Artifact).filter(Artifact.project_id == project_id).count()


def test_medium_write_artifact_executes_directly(session_factory):
    session = session_factory()
    project = _project(session)
    action = CreativeAction(operation="write_artifact", kind="story_graph", payload={"content": {"title": "v1"}})
    assert action.risk() == "medium"
    out = ActionExecution(session).execute(project.id, action)
    assert out["status"] == "executed"
    assert out["artifact"] == {"kind": "story_graph", "version": 1}
    assert out["transaction_id"]
    session.expire_all()
    assert _count(session, project.id) == 1
    session.close()


def test_apply_effects_transactional(session_factory):
    session = session_factory()
    project = _project(session)
    ps = PlayerSession(project_id=project.id, current_node_id="start", state={"affection": 0})
    session.add(ps)
    session.commit()
    action = CreativeAction(
        operation="apply_effects",
        payload={"session_id": ps.id, "effects": [{"variable": "affection", "op": "add", "value": 3}]},
    )
    out = ActionExecution(session).execute(project.id, action)
    assert out["status"] == "executed"
    assert out["state"]["affection"] == 3
    session.expire_all()
    assert session.get(PlayerSession, ps.id).state["affection"] == 3
    session.close()


def test_high_risk_requires_confirmation(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_versions(session, project.id)
    action = CreativeAction(operation="revert_artifact", kind="story_graph", payload={"version": 1})
    assert action.risk() == "high"
    out = ActionExecution(session).execute(project.id, action)
    assert out["status"] == "pending" and out["proposal_id"]
    session.expire_all()
    # 未执行：仍只有 3 个版本
    assert _count(session, project.id) == 3
    prop = session.get(ActionProposal, out["proposal_id"])
    assert prop.status == "pending" and prop.risk == "high"
    session.close()


def test_confirm_executes_governance(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_versions(session, project.id)
    out = ActionExecution(session).execute(
        project.id, CreativeAction(operation="revert_artifact", kind="story_graph", payload={"version": 1}),
    )
    result = ActionExecution(session).confirm(out["proposal_id"])
    assert result["status"] == "executed"
    assert result["governance"]["version"] == 4
    session.expire_all()
    assert _count(session, project.id) == 4  # revert = 追加新版本
    assert session.get(ActionProposal, out["proposal_id"]).status == "executed"
    session.close()


def test_reject_proposal(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_versions(session, project.id)
    out = ActionExecution(session).execute(
        project.id, CreativeAction(operation="promote_artifact", kind="story_graph", payload={"version": 1}),
    )
    result = ActionExecution(session).reject(out["proposal_id"])
    assert result["status"] == "rejected"
    session.expire_all()
    assert session.get(ActionProposal, out["proposal_id"]).status == "rejected"
    assert _count(session, project.id) == 3
    session.close()


def test_locked_content_blocked(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_locked(session, project.id)
    action = CreativeAction(operation="write_artifact", kind="story_graph", node_id="n1", payload={"content": {}})
    with pytest.raises(AppError) as e:
        ActionExecution(session).execute(project.id, action)
    assert e.value.code == "locked_node" and e.value.status == 409
    session.expire_all()
    assert _count(session, project.id) == 1  # 仅锁定节点那个 story_graph，未新增
    session.close()


def test_proposal_double_confirm_conflict(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_versions(session, project.id)
    out = ActionExecution(session).execute(
        project.id, CreativeAction(operation="revert_artifact", kind="story_graph", payload={"version": 1}),
    )
    ActionExecution(session).confirm(out["proposal_id"])
    with pytest.raises(AppError) as e:
        ActionExecution(session).confirm(out["proposal_id"])
    assert e.value.code == "proposal_not_pending" and e.value.status == 409
    session.close()


def test_unknown_action_rejected(session_factory):
    session = session_factory()
    project = _project(session)
    action = CreativeAction(operation="no_such_op")
    with pytest.raises(AppError) as e:
        ActionExecution(session).execute(project.id, action)
    assert e.value.code == "invalid_action"
    session.close()


def test_action_api_hitl(client, session_factory):
    session = session_factory()
    project = _project(session)
    _seed_versions(session, project.id)
    session.close()
    # 高风险 → pending
    resp = client.post(f"/api/projects/{project.id}/actions",
                       json={"operation": "revert_artifact", "kind": "story_graph", "payload": {"version": 1}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending" and body["proposal_id"]
    # 确认 → executed
    resp = client.post(f"/api/projects/{project.id}/actions/proposals/{body['proposal_id']}/confirm")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "executed" and resp.json()["governance"]["version"] == 4