"""API：增强世界图试玩（增量：InkOS 互动影游核心 · 干净移植）。

与 Step20 的简化 Play（/play/sessions）互补：本模块提供 InkOS 风格的
「类型化实体 + 时间有效性关系边 + 状态槽种类 + 证据状态单向推进」世界图。
权威数据 = Artifact(kind="world_play:{play_id}")，每回合落新版本（可回溯），读取取 latest。
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.models import Artifact, Project
from app.schemas.play import PlayMutation, PlayWorld, apply_play_mutation, new_world
from app.services.artifacts import latest_artifact, persist_versioned_artifact

router = APIRouter(prefix="/api/projects")

_AGENT = "world_play_runtime"
_TASK = "world_play"


def _kind(play_id: str) -> str:
    return f"world_play:{play_id}"


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


def _load(session: Session, project_id: str, play_id: str) -> tuple[PlayWorld, int]:
    artifact = latest_artifact(session, project_id, kind=_kind(play_id))
    if artifact is None:
        raise AppError("世界图试玩会话不存在", code="world_play_not_found", status=404)
    content = artifact.content or {}
    world = PlayWorld.model_validate(content) if content else new_world()
    return world, artifact.version


def _save(session: Session, project_id: str, play_id: str, world: PlayWorld, reason: str) -> int:
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_kind(play_id),
        content=world.model_dump(), prompt_version="", source="agent", change_reason=reason,
    )
    session.commit()
    return artifact.version


class WorldPlayStartInput(BaseModel):
    kind: str = "open_world"
    title: str = ""
    seed: PlayMutation | None = None
    raw_input: str = ""


class WorldPlayStepInput(BaseModel):
    mutation: PlayMutation
    raw_input: str = ""


@router.post("/{project_id}/worldplay/start")
def world_play_start(project_id: str, payload: WorldPlayStartInput, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    play_id = uuid.uuid4().hex[:16]
    kind = payload.kind if payload.kind in ("open_world", "branching") else "open_world"
    world = new_world(kind=kind, title=payload.title)
    if payload.seed is not None:
        result = apply_play_mutation(world, payload.seed, payload.raw_input or "（世界初始化）")
        world = result["world"]
    version = _save(session, project_id, play_id, world, "world_play_start")
    return {"play_id": play_id, "version": version, "world": world.model_dump()}


@router.post("/{project_id}/worldplay/{play_id}/step")
def world_play_step(
    project_id: str, play_id: str, payload: WorldPlayStepInput, session: Session = Depends(get_session)
) -> dict:
    _require_project(session, project_id)
    world, _ = _load(session, project_id, play_id)
    try:
        result = apply_play_mutation(world, payload.mutation, payload.raw_input)
    except ValueError as e:
        raise AppError(str(e), code="world_play_mutation_invalid", status=422) from e
    version = _save(session, project_id, play_id, result["world"], f"world_play_step:{payload.mutation.event_id}")
    return {
        "play_id": play_id, "version": version,
        "world": result["world"].model_dump(),
        "event": result["event"].model_dump(),
        "blocked": result["blocked"],
    }


@router.get("/{project_id}/worldplay/{play_id}")
def world_play_state(project_id: str, play_id: str, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    world, version = _load(session, project_id, play_id)
    return {"play_id": play_id, "version": version, "world": world.model_dump()}


@router.get("/{project_id}/worldplay")
def world_play_list(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    _require_project(session, project_id)
    rows = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.kind.like("world_play:%"), Artifact.is_latest.is_(True))
        .order_by(Artifact.created_at.desc())
        .all()
    )
    out: list[dict] = []
    for a in rows:
        content = a.content or {}
        out.append({
            "play_id": a.kind.split(":", 1)[1],
            "kind": content.get("kind", "open_world"),
            "title": content.get("title", ""),
            "turn": content.get("turn", 0),
            "version": a.version,
        })
    return out