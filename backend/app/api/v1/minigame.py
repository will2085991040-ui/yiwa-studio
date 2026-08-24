"""API：小游戏节点 + postMessage 结果协议（增量：Funloom 蒸馏 · Phase 4）。

小游戏在 iframe 中运行，完成时向父页 postMessage(`funloom:minigame:complete`)；
父页 Runtime 调用本模块的 `minigame-result` 端点落状态，然后用节点 choices 继续推进。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.models import PlayerSession, Project
from app.runtime.session_service import runtime_choices
from app.runtime.state import StateManager
from app.schemas.minigame import (
    RESULT_STATE_KEY,
    SCORE_STATE_KEY,
    MinigameResultInput,
    minigame_protocol,
)
from app.services.artifacts import latest_artifact

router = APIRouter(prefix="/api")


def _story_graph(session: Session, project_id: str) -> dict:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    return story.content or {}


@router.get("/meta/minigame-protocol")
def protocol() -> dict:
    return minigame_protocol()


@router.post("/projects/{project_id}/runtime/sessions/{session_id}/minigame-result")
def submit_minigame_result(
    project_id: str, session_id: str, payload: MinigameResultInput, session: Session = Depends(get_session)
) -> dict:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")
    ps = (
        session.query(PlayerSession)
        .filter(PlayerSession.id == session_id, PlayerSession.project_id == project_id)
        .first()
    )
    if ps is None:
        raise AppError("会话不存在", code="session_not_found", status=404)

    graph = _story_graph(session, project_id)
    node = next((n for n in graph.get("nodes", []) if n.get("node_id") == ps.current_node_id), None)
    if node is None:
        raise AppError(f"当前节点 {ps.current_node_id} 不存在", code="node_not_found", status=404)
    config = node.get("minigame")
    if not config:
        raise AppError("当前节点不是小游戏节点", code="not_minigame_node", status=422)

    sm = StateManager(session, ps)
    # 保留键：小游戏结果（success|perfect）+ 可选得分
    sm.set_state_value(RESULT_STATE_KEY, payload.result)
    if payload.score is not None:
        sm.set_state_value(SCORE_STATE_KEY, payload.score)
        score_var = (config or {}).get("score_variable")
        if score_var and score_var in sm.get_state():
            sm.apply_effect({"variable": score_var, "op": "set", "value": payload.score})
    committed = sm.commit()
    session.commit()

    return {
        "session": {
            "session_id": ps.id, "project_id": ps.project_id,
            "current_node_id": ps.current_node_id, "state": committed,
        },
        "node": {"node_id": node.get("node_id"), "kind": node.get("kind"), "title": node.get("title")},
        "minigame": config,
        "last_result": payload.result,
        "choices": runtime_choices(session, project_id, session_id),
    }