"""PlayerSession 服务（Step 13）：互动游玩的最小会话编排。

职责边界：
- 只读 Authoring（读取最新 story_graph Artifact）＋ 调用 StateManager 提交状态
- 不直接改 state：所有效果落地都经 StateManager（唯一提交入口）
- 不调用任何 LLM / Agent；Choice 的 Condition/Effect 由确定性代码求值/应用
"""
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models import PlayerSession, Project
from app.runtime.engine import parse_condition
from app.runtime.state import StateManager
from app.services.artifacts import latest_artifact
from app.trace.manager import trace_manager


def _story_graph(session: Session, project_id: str) -> dict:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    return story.content or {}


def _locate_node(graph: dict, node_id: str) -> dict | None:
    return next((n for n in graph.get("nodes", []) if n.get("node_id") == node_id), None)


def _get_ps(session: Session, project_id: str, session_id: str) -> PlayerSession:
    ps = (
        session.query(PlayerSession)
        .filter(PlayerSession.id == session_id, PlayerSession.project_id == project_id)
        .first()
    )
    if ps is None:
        raise AppError("会话不存在", code="session_not_found", status=404)
    return ps


def _session_out(ps: PlayerSession) -> dict:
    return {
        "session_id": ps.id,
        "project_id": ps.project_id,
        "current_node_id": ps.current_node_id,
        "state": dict(ps.state or {}),
        "created_at": ps.created_at,
    }


def create_runtime_session(session: Session, project_id: str) -> dict:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    graph = _story_graph(session, project_id)
    entry = graph.get("entry_node_id")
    if not entry:
        raise AppError("StoryGraph 缺少 entry_node_id，无法创建会话", code="no_entry_node", status=400)
    if _locate_node(graph, entry) is None:
        raise AppError(f"entry_node_id {entry} 不存在", code="node_not_found", status=404)

    initial = StateManager.create_initial_state(graph.get("variables", []))
    ps = PlayerSession(project_id=project_id, current_node_id=entry, state=initial)
    run = trace_manager.start_run(session, kind="runtime_create", meta={"project_id": project_id})
    session.add(ps)
    session.flush()
    trace_manager.add_step(
        session, run, agent="runtime", step_key="session_create",
        input_data={"project_id": project_id},
        output_data={"session_id": ps.id, "current_node_id": entry, "state": initial},
    )
    trace_manager.finish_run(run, status="ok")
    session.commit()
    return _session_out(ps)


def get_runtime_session(session: Session, project_id: str, session_id: str) -> dict:
    return _session_out(_get_ps(session, project_id, session_id))


def runtime_choices(session: Session, project_id: str, session_id: str) -> list[dict]:
    ps = _get_ps(session, project_id, session_id)
    graph = _story_graph(session, project_id)
    return StateManager(session, ps).get_visible_choices(graph, ps.current_node_id)


def choose_choice(session: Session, project_id: str, session_id: str, choice_id: str) -> dict:
    ps = _get_ps(session, project_id, session_id)
    graph = _story_graph(session, project_id)
    node = _locate_node(graph, ps.current_node_id)
    if node is None:
        raise AppError(f"当前节点 {ps.current_node_id} 不存在于 StoryGraph", code="node_not_found", status=404)
    choice = next((c for c in node.get("choices", []) if c.get("choice_id") == choice_id), None)
    if choice is None:
        raise AppError(f"节点 {node.get('node_id')} 中不存在选择 {choice_id}", code="choice_not_found", status=404)

    sm = StateManager(session, ps)

    # Condition 由确定性代码求值（不是 LLM，不是 eval）
    raw = choice.get("condition")
    if raw is not None and not (isinstance(raw, str) and raw.strip() == ""):
        parsed = parse_condition(raw if isinstance(raw, str) else "")
        if parsed is None:
            raise AppError("该选择的条件无法安全求值", code="unevaluable_condition", status=422)
        if not sm.evaluate_condition(parsed):
            raise AppError("该选择的条件不满足", code="condition_not_met", status=422)

    next_node_id = choice.get("next_node") or ps.current_node_id
    node_ids = {n.get("node_id") for n in graph.get("nodes", [])}
    if next_node_id not in node_ids:
        raise AppError(f"next_node {next_node_id} 不存在于 StoryGraph", code="next_node_not_found", status=422)

    previous_state = sm.get_state()
    effects = choice.get("effects", [])
    sm.apply_effects(effects)
    committed = sm.commit()          # StateManager 是唯一提交入口
    ps.current_node_id = next_node_id

    run = trace_manager.start_run(session, kind="runtime_choice", meta={"session_id": session_id})
    trace_manager.add_step(
        session, run, agent="runtime", step_key="choice",
        input_data={"session_id": session_id, "node_id": node.get("node_id"), "choice_id": choice_id},
        output_data={
            "previous_state": previous_state,
            "applied_effects": effects,
            "next_node_id": next_node_id,
            "state": committed,
        },
    )
    trace_manager.finish_run(run, status="ok")
    session.commit()
    return _session_out(ps)