"""Step 14 测试：Creative Transaction 原子闭环 + Version Governance（promote/revert/compare）。"""
import pytest

from app.core.errors import AppError
from app.models import AgentRun, AgentStep, Artifact, PlayerSession, Project
from app.runtime.state import StateManager
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.governance import (
    ContentGovernance,
    compare_artifacts,
    promote_artifact,
    revert_artifact,
)
from app.services.transaction import CreativeTransaction

GOAL = "制作一个乙女悬疑Galgame，5 章，3 结局，玩家选择影响好感度与结局。"


def _project(session) -> Project:
    project = Project(goal=GOAL, template="galgame")
    session.add(project)
    session.commit()
    return project


def _add_version(session, project_id, *, content, source="agent", change_reason=None) -> Artifact:
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id="s4", agent="plot", kind="story_graph",
        content=content, prompt_version="plot_generation:v1", source=source, change_reason=change_reason,
    )
    session.commit()
    return artifact


def _seed_three_versions(session) -> Project:
    """story_graph v1/v2/v3，latest=v3。内容与元数据各不相同。"""
    project = _project(session)
    _add_version(session, project.id, content={"title": "v1", "genre": "乙女"})
    _add_version(session, project.id, content={"title": "v2", "genre": "乙女", "tone": "甜"},
                 source="user", change_reason="改甜")
    _add_version(session, project.id, content={"title": "v3", "genre": "悬疑"})
    return project


def _txn_project(session) -> tuple[Project, PlayerSession]:
    project = _project(session)
    ps = PlayerSession(project_id=project.id, current_node_id="start", state={"affection": 0, "trust": 0})
    session.add(ps)
    session.commit()
    return project, ps


def _story_count(session, project_id) -> int:
    return session.query(Artifact).filter(
        Artifact.project_id == project_id, Artifact.kind == "story_graph",
    ).count()


# ---------------------------------------------------------------------------
# Transaction（1–8）
# ---------------------------------------------------------------------------


def test_transaction_success_commits_all(session_factory):
    """Artifact + Runtime State + Trace 全部成功提交，且带 transaction_id。"""
    session = session_factory()
    project, ps = _txn_project(session)
    with CreativeTransaction(session, project_id=project.id, operation="opsuccess") as txn:
        txn.validate([("schema", lambda: None)])
        art = txn.stage_artifact(
            task_id="s4", agent="plot", kind="story_graph", content={"title": "v1"}, prompt_version="pv:1",
        )
        sm = StateManager(session, ps)
        txn.stage_state(sm, [{"variable": "affection", "op": "add", "value": 5}])
        txn.add_trace_step(
            agent="plot", step_key="artifact", input_data={"goal": GOAL}, output_data={"version": art.version},
        )
    session.expire_all()
    # Artifact commit 成功
    assert _story_count(session, project.id) == 1
    # State commit 成功
    assert session.get(PlayerSession, ps.id).state["affection"] == 5
    # Trace commit 成功 + transaction_id
    run = session.query(AgentRun).filter(AgentRun.kind == "txn_opsuccess").one()
    assert run.status == "ok"
    assert run.meta["transaction_id"] == txn.transaction_id
    summary = session.query(AgentStep).filter(
        AgentStep.agent_run_id == run.id, AgentStep.step_key == "txn.summary",
    ).one()
    assert summary.output_data["transaction_id"] == txn.transaction_id
    assert summary.output_data["artifact_changes"] == [{"kind": "story_graph", "version": 1}]
    assert summary.output_data["runtime_state_changes"][0]["state"]["affection"] == 5
    session.close()


def test_transaction_artifact_commit_success(session_factory):
    session = session_factory()
    project = _project(session)
    with CreativeTransaction(session, project_id=project.id, operation="artcommit") as txn:
        txn.stage_artifact(
            task_id="s4", agent="plot", kind="story_graph", content={"title": "v1"}, prompt_version="pv:1",
        )
    session.expire_all()
    assert _story_count(session, project.id) == 1
    assert latest_artifact(session, project.id, kind="story_graph").version == 1
    session.close()


def test_transaction_state_commit_success(session_factory):
    session = session_factory()
    project, ps = _txn_project(session)
    with CreativeTransaction(session, project_id=project.id, operation="statecommit") as txn:
        txn.stage_state(StateManager(session, ps), [{"variable": "trust", "op": "add", "value": 2}])
    session.expire_all()
    assert session.get(PlayerSession, ps.id).state == {"affection": 0, "trust": 2}
    session.close()


def test_transaction_validate_failure_rollback(session_factory):
    """校验失败 → 回滚：不产生 Artifact、不留成功 Trace。"""
    session = session_factory()
    project, ps = _txn_project(session)

    def _bad():
        raise ValueError("schema 不符合")

    with pytest.raises(AppError) as e:
        with CreativeTransaction(session, project_id=project.id, operation="valfail") as txn:
            txn.validate([("schema", _bad)])
            txn.stage_artifact(task_id="s4", agent="plot", kind="story_graph", content={"t": 1}, prompt_version="pv:1")
    assert e.value.code == "validation_failed"
    session.expire_all()
    assert _story_count(session, project.id) == 0
    _assert_only_rollback_trace(session, "txn_valfail")
    session.close()


def test_transaction_artifact_failure_rollback(session_factory):
    """Artifact 已写入（flush）后失败 → 不产生新版本。"""
    session = session_factory()
    project, ps = _txn_project(session)
    with pytest.raises(AppError):
        with CreativeTransaction(session, project_id=project.id, operation="artfail") as txn:
            txn.stage_artifact(task_id="s4", agent="plot", kind="story_graph", content={"t": 1}, prompt_version="pv:1")
            raise AppError("模拟 artifact 提交失败", code="boom")
    session.expire_all()
    assert _story_count(session, project.id) == 0
    _assert_only_rollback_trace(session, "txn_artfail")
    session.close()


def test_transaction_state_failure_rollback(session_factory):
    """State 提交失败 → Artifact 一并回滚、Runtime State 不变。"""
    session = session_factory()
    project, ps = _txn_project(session)
    with pytest.raises(AppError):
        with CreativeTransaction(session, project_id=project.id, operation="statefail") as txn:
            txn.stage_artifact(
                task_id="s4", agent="plot", kind="story_graph", content={"t": 1}, prompt_version="pv:1",
            )
            # 未定义变量 → apply_effect 抛错，触发整体回滚
            txn.stage_state(StateManager(session, ps), [{"variable": "missing", "op": "add", "value": 1}])
    session.expire_all()
    assert _story_count(session, project.id) == 0          # Artifact 也回滚
    assert session.get(PlayerSession, ps.id).state["affection"] == 0  # State 未变
    _assert_only_rollback_trace(session, "txn_statefail")
    session.close()


def test_transaction_final_failure_rollback(session_factory):
    """Artifact + State + Trace 均已准备后最终失败 → 三者全部回滚。"""
    session = session_factory()
    project, ps = _txn_project(session)
    with pytest.raises(AppError):
        with CreativeTransaction(session, project_id=project.id, operation="finalfail") as txn:
            txn.stage_artifact(task_id="s4", agent="plot", kind="story_graph", content={"t": 1}, prompt_version="pv:1")
            txn.stage_state(StateManager(session, ps), [{"variable": "affection", "op": "add", "value": 5}])
            txn.add_trace_step(agent="plot", step_key="artifact", input_data={}, output_data={})
            raise AppError("模拟最终提交失败", code="final_fail")
    session.expire_all()
    assert _story_count(session, project.id) == 0
    assert session.get(PlayerSession, ps.id).state["affection"] == 0
    _assert_only_rollback_trace(session, "txn_finalfail")
    session.close()


def _assert_only_rollback_trace(session, kind: str) -> None:
    """回滚后：只有一条 status=failed 且 rollback=True 的 Trace，绝不伪装成功。"""
    runs = session.query(AgentRun).filter(AgentRun.kind == kind).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].meta.get("rollback") is True
    assert session.query(AgentStep).filter(AgentStep.agent_run_id == runs[0].id).count() >= 1


# ---------------------------------------------------------------------------
# Version Governance（9–16）
# ---------------------------------------------------------------------------


def test_compare_two_versions(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    out = compare_artifacts(session, project_id=project.id, kind="story_graph", version_a=1, version_b=2)
    assert out["version_a"] == 1 and out["version_b"] == 2
    assert isinstance(out["content_diff"], dict) and isinstance(out["metadata_diff"], dict)
    session.close()


def test_compare_content_diff(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    out = compare_artifacts(session, project_id=project.id, kind="story_graph", version_a=1, version_b=3)
    changed = out["content_diff"]["changed"]
    assert changed["genre"] == {"from": "乙女", "to": "悬疑"}
    assert changed["title"] == {"from": "v1", "to": "v3"}
    session.close()


def test_compare_metadata_diff(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    out = compare_artifacts(session, project_id=project.id, kind="story_graph", version_a=1, version_b=2)
    changed = out["metadata_diff"]["changed"]
    assert changed["source"] == {"from": "agent", "to": "user"}
    assert changed["change_reason"] == {"from": None, "to": "改甜"}
    assert changed["parent_version"] == {"from": None, "to": 1}
    session.close()


def test_promote_old_version(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    out = promote_artifact(session, project_id=project.id, kind="story_graph", version=1)
    assert out["version"] == 1 and out["is_latest"] is True
    session.expire_all()
    assert latest_artifact(session, project.id, kind="story_graph").version == 1
    session.close()


def test_promote_single_latest(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    promote_artifact(session, project_id=project.id, kind="story_graph", version=1)
    session.expire_all()
    rows = session.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.kind == "story_graph",
    ).all()
    assert len(rows) == 3  # 历史不删除
    assert sum(1 for r in rows if r.is_latest) == 1
    assert next(r for r in rows if r.is_latest).version == 1
    session.close()


def test_revert_keeps_history(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    revert_artifact(session, project_id=project.id, kind="story_graph", version=1)
    session.expire_all()
    versions = [
        r.version for r in session.query(Artifact).filter(
            Artifact.project_id == project.id, Artifact.kind == "story_graph",
        ).order_by(Artifact.version).all()
    ]
    assert versions == [1, 2, 3, 4]  # 历史全部保留，绝不删除
    session.close()


def test_revert_new_version_parent_and_content(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    out = revert_artifact(session, project_id=project.id, kind="story_graph", version=1)
    assert out["version"] == 4
    session.expire_all()
    v4 = session.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.kind == "story_graph", Artifact.version == 4,
    ).one()
    assert v4.is_latest is True
    assert v4.parent_version == 3                        # parent 指向版本链顶端 v3
    assert v4.content == {"title": "v1", "genre": "乙女"}  # 内容 = v1
    assert v4.change_reason == "revert:v1"
    assert v4.source == "user"
    rows = session.query(Artifact).filter(
        Artifact.project_id == project.id, Artifact.kind == "story_graph",
    ).all()
    assert sum(1 for r in rows if r.is_latest) == 1      # 唯一 latest
    session.close()


# ---------------------------------------------------------------------------
# Content Governance（17–20）
# ---------------------------------------------------------------------------


def _seed_locked_story(session, project_id) -> None:
    story = {
        "entry_node_id": "n1",
        "variables": [{"name": "affection", "type": "number", "initial": 0, "description": ""}],
        "nodes": [
            {"node_id": "n1", "kind": "scene", "title": "锁定的起点", "summary": "", "locked": True, "choices": []},
            {"node_id": "n2", "kind": "scene", "title": "未锁定", "summary": "", "choices": []},
        ],
        "edges": [], "metadata": {},
    }
    persist_versioned_artifact(
        session, project_id=project_id, task_id="s4", agent="plot",
        kind="story_graph", content=story, prompt_version="pv:1",
    )
    session.commit()


def test_locked_node_not_editable(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_locked_story(session, project.id)
    gov = ContentGovernance(session, project.id)
    with pytest.raises(AppError) as e:
        gov.assert_editable("n1")
    assert e.value.code == "locked_node" and e.value.status == 409
    gov.assert_editable("n2")   # 未锁定 → 不抛
    gov.assert_editable(None)   # 无 node_id → 不抛
    session.close()


def test_version_not_found(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)
    with pytest.raises(AppError) as e:
        compare_artifacts(session, project_id=project.id, kind="story_graph", version_a=1, version_b=99)
    assert e.value.code == "version_not_found" and e.value.status == 404
    with pytest.raises(AppError) as e:
        promote_artifact(session, project_id=project.id, kind="story_graph", version=99)
    assert e.value.code == "version_not_found"
    with pytest.raises(AppError) as e:
        revert_artifact(session, project_id=project.id, kind="story_graph", version=99)
    assert e.value.code == "version_not_found"
    session.close()


def test_artifact_kind_not_found(session_factory):
    session = session_factory()
    project = _project(session)  # 无任何 artifact
    with pytest.raises(AppError) as e:
        promote_artifact(session, project_id=project.id, kind="world_bible", version=1)
    assert e.value.code == "artifact_not_found" and e.value.status == 404
    with pytest.raises(AppError) as e:
        compare_artifacts(session, project_id=project.id, kind="world_bible", version_a=1, version_b=2)
    assert e.value.code == "artifact_not_found"
    session.close()


def test_version_conflict(session_factory):
    session = session_factory()
    project = _seed_three_versions(session)  # latest=v3
    with pytest.raises(AppError) as e:
        revert_artifact(session, project_id=project.id, kind="story_graph", version=1, expected_latest=2)
    assert e.value.code == "version_conflict" and e.value.status == 409
    out = revert_artifact(session, project_id=project.id, kind="story_graph", version=1, expected_latest=3)
    assert out["version"] == 4
    session.close()


# ---------------------------------------------------------------------------
# Runtime 并入事务（21–22）
# ---------------------------------------------------------------------------


def test_runtime_state_and_artifact_same_transaction(session_factory):
    session = session_factory()
    project, ps = _txn_project(session)
    with CreativeTransaction(session, project_id=project.id, operation="runtimecreate") as txn:
        txn.stage_artifact(
            task_id="s4", agent="plot", kind="story_graph", content={"title": "v1"}, prompt_version="pv:1",
        )
        txn.stage_state(StateManager(session, ps), [{"variable": "affection", "op": "add", "value": 3}])
    session.expire_all()
    assert _story_count(session, project.id) == 1
    assert session.get(PlayerSession, ps.id).state["affection"] == 3
    session.close()


def test_runtime_failure_rolls_back_artifact_too(session_factory):
    session = session_factory()
    project, ps = _txn_project(session)
    with pytest.raises(AppError):
        with CreativeTransaction(session, project_id=project.id, operation="runtimefail") as txn:
            txn.stage_artifact(
                task_id="s4", agent="plot", kind="story_graph", content={"title": "v1"}, prompt_version="pv:1",
            )
            txn.stage_state(StateManager(session, ps), [{"variable": "missing", "op": "add", "value": 1}])
    session.expire_all()
    assert _story_count(session, project.id) == 0          # Artifact 也回滚
    assert session.get(PlayerSession, ps.id).state["affection"] == 0  # State 不变化
    _assert_only_rollback_trace(session, "txn_runtimefail")
    session.close()


# ---------------------------------------------------------------------------
# API（compare / promote / revert）
# ---------------------------------------------------------------------------


def test_governance_api_loop(client, session_factory):
    session = session_factory()
    project = _seed_three_versions(session)  # v1/v2/v3, latest=v3
    session.close()

    # compare
    resp = client.post(f"/api/projects/{project.id}/artifacts/compare",
                       json={"kind": "story_graph", "version_a": 1, "version_b": 3})
    assert resp.status_code == 200, resp.text
    assert resp.json()["content_diff"]["changed"]["genre"] == {"from": "乙女", "to": "悬疑"}

    # promote v1 → 唯一 latest
    resp = client.post(f"/api/projects/{project.id}/artifacts/promote",
                       json={"kind": "story_graph", "version": 1})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_latest"] is True and resp.json()["version"] == 1

    # revert v1 → 新增 v4（parent=版本链顶端 v3，内容=v1）
    resp = client.post(f"/api/projects/{project.id}/artifacts/revert",
                       json={"kind": "story_graph", "version": 1})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == 4 and body["parent_version"] == 3 and body["is_latest"] is True

    # 乐观并发冲突：当前 latest 已是 v4，期望 v1 → 409
    resp = client.post(f"/api/projects/{project.id}/artifacts/revert",
                       json={"kind": "story_graph", "version": 1, "expected_latest": 1})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "version_conflict"