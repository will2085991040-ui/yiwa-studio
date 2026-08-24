"""Step 15 测试：Context Compiler（统一上下文装配）+ Memory（BM25 检索，Truth/Index 分离）。"""
import pytest

from app.core.errors import AppError
from app.models import MemoryEntry, Project
from app.services.artifacts import persist_versioned_artifact
from app.services.context_compiler import L0, L1, L2, L3, L5, L6, LAYERS, ContextCompiler
from app.services.memory import MEMORY_KINDS, memory_store


def test_memory_forget_and_list_kind(session_factory):
    session = session_factory()
    project = _project(session)
    m = memory_store.remember(
        session, project.id, kind="character", content="女主", ref_kind="character_card", ref_id="c1",
    )
    session.commit()
    assert len(memory_store.list_kind(session, project.id, "character")) == 1
    memory_store.forget(session, m.id)
    session.commit()
    assert memory_store.list_kind(session, project.id, "character") == []
    assert memory_store.search(session, project.id, "女主") == []
    # ASCII 词条 + 无命中词（dft==0 分支）
    memory_store.remember(session, project.id, kind="scene", content="courtroom drama")
    session.commit()
    assert memory_store.search(session, project.id, "courtroom nomatchterm")[0]["kind"] == "scene"
    session.close()


def test_memory_invalid_forget(session_factory):
    session = session_factory()
    with pytest.raises(AppError) as e:
        memory_store.forget(session, "no-such-memory")
    assert e.value.code == "memory_not_found"
    session.close()


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
            {"node_id": "n1", "kind": "scene", "title": "起点", "summary": "",
             "choices": [{"choice_id": "c1", "text": "前进", "effects": [], "next_node": "n2"}]},
            {"node_id": "n2", "kind": "ending", "title": "结局", "summary": ""},
        ],
        "edges": [], "metadata": {},
    }
    persist_versioned_artifact(
        session, project_id=project_id, task_id="s4", agent="plot",
        kind="story_graph", content=story, prompt_version="pv:1",
    )
    session.commit()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


def test_memory_remember_and_search(session_factory):
    session = session_factory()
    project = _project(session)
    memory_store.remember(
        session, project.id, kind="character",
        content="乙女游戏里傲娇女主林小满对男主心动。",
        ref_kind="character_card", ref_id="c1", tags=["乙女", "女主"],
    )
    memory_store.remember(session, project.id, kind="foreshadow", content="调查员隐藏身份是关键伏笔。", tags=["悬疑"])
    memory_store.remember(
        session, project.id, kind="scene", content="娱乐公司面试场景，位于顶楼会议室。", tags=["公司"],
    )
    session.commit()
    results = memory_store.search(session, project.id, "傲娇女主 心动")
    assert results and results[0]["kind"] == "character"
    assert "傲娇" in results[0]["content"]
    assert results[0]["score"] > 0
    session.close()


def test_memory_search_empty(session_factory):
    session = session_factory()
    project = _project(session)
    assert memory_store.search(session, project.id, "任何查询") == []
    session.close()


def test_memory_points_to_truth(session_factory):
    session = session_factory()
    project = _project(session)
    entry = memory_store.remember(
        session, project.id, kind="character", content="角色摘要",
        ref_kind="character_card", ref_id="char-001", tags=["主角"],
    )
    session.commit()
    row = session.get(MemoryEntry, entry.id)
    assert row.ref_kind == "character_card" and row.ref_id == "char-001"  # 索引回指 truth
    assert row.kind in MEMORY_KINDS
    session.close()


def test_memory_invalid_kind(session_factory):
    session = session_factory()
    project = _project(session)
    with pytest.raises(AppError) as e:
        memory_store.remember(session, project.id, kind="not_a_kind", content="x")
    assert e.value.code == "invalid_memory_kind"
    session.close()


# ---------------------------------------------------------------------------
# Context Compiler
# ---------------------------------------------------------------------------


def test_context_layers_all_present(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_story(session, project.id)
    out = ContextCompiler(session).compile(project.id, instruction="写对白")
    for key in LAYERS:
        assert key in out["layers"]
    assert isinstance(out["token_estimate"], int) and out["token_estimate"] > 0
    assert out["layers"][L0] and out["layers"][L6] == "写对白"
    session.close()


def test_context_missing_scene_not_fabricated(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_story(session, project.id)  # 有 story_graph，但没有 scene:n1
    out = ContextCompiler(session).compile(project.id)
    assert "scene:n1" in out["missing"]
    assert "禁止伪造" in out["layers"][L3]  # 缺失 → 诚实标记
    session.close()


def test_context_missing_story_graph(session_factory):
    session = session_factory()
    project = _project(session)  # 无任何 artifact
    out = ContextCompiler(session).compile(project.id)
    assert "story_graph" in out["missing"]
    session.close()


def test_context_budget_trims_low_priority(session_factory):
    session = session_factory()
    project = _project(session)
    _seed_story(session, project.id)
    out = ContextCompiler(session).compile(
        project.id, token_budget=150, runtime_state={"pad": "x" * 1200},
    )
    assert L5 in out["trimmed"]          # runtime state 是低优先级
    assert L3 not in out["trimmed"]      # current focus 保留
    assert L2 not in out["trimmed"]      # 结构骨架保留
    assert L0 not in out["trimmed"] and L1 not in out["trimmed"]
    session.close()


def test_context_api(client, session_factory):
    session = session_factory()
    project = _project(session)
    _seed_story(session, project.id)
    session.close()
    resp = client.post(f"/api/projects/{project.id}/context/compile", json={"instruction": "扩展剧情"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(LAYERS) <= set(body["layers"].keys())
    assert "scene:n1" in body["missing"]