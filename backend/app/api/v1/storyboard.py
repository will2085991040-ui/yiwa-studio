"""API：分镜拆镜 + 视频生成（增量：Funloom 蒸馏 · Phase 3）。

权威数据 = Artifact(kind="storyboard:{node_id}") 与 Artifact(kind="video_job:{node_id}")，
复用既有 versioned artifact 链。视频生成为确定性 mock（离线计价 + 状态），不冒充真实渲染。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.media.types import VideoRequest
from app.media.video import poll_video, submit_video
from app.models import Project
from app.schemas.storyboard import (
    COST_PER_SECOND,
    Storyboard,
    VideoJob,
    compose_seedance_prompt,
    compose_shot_prompt,
    storyboard_template,
)
from app.services.artifacts import latest_artifact, persist_versioned_artifact
from app.services.storyboard_service import run_storyboard_breakdown

router = APIRouter(prefix="/api")

_AGENT = "storyboard_editor"
_TASK = "storyboard_editor"


def _sb_kind(node_id: str) -> str:
    return f"storyboard:{node_id}"


def _vj_kind(node_id: str) -> str:
    return f"video_job:{node_id}"


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


def _load_storyboard(session: Session, project_id: str, node_id: str) -> tuple[Storyboard, int]:
    artifact = latest_artifact(session, project_id, kind=_sb_kind(node_id))
    if artifact is None:
        return Storyboard(node_id=node_id), 0
    return Storyboard.model_validate(artifact.content or {"node_id": node_id}), artifact.version


def _sb_view(storyboard: Storyboard, version: int) -> dict:
    d = storyboard.model_dump()
    d["version"] = version
    d["shot_prompts"] = {s.shot_no: compose_shot_prompt(s) for s in storyboard.shots}
    d["seedance_prompt"] = compose_seedance_prompt(storyboard)
    return d


class BreakdownInput(BaseModel):
    requested_shots: int = 4


class SaveInput(BaseModel):
    storyboard: Storyboard
    change_reason: str | None = None


class VideoGenInput(BaseModel):
    duration_sec: float | None = None
    aspect_ratio: str = "16:9"  # 16:9 横屏 / 9:16 竖屏


@router.get("/meta/storyboard-template")
def template() -> dict:
    return storyboard_template()


@router.get("/projects/{project_id}/storyboard/{node_id}")
def get_storyboard(project_id: str, node_id: str, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    sb, version = _load_storyboard(session, project_id, node_id)
    return _sb_view(sb, version)


@router.put("/projects/{project_id}/storyboard/{node_id}")
def put_storyboard(
    project_id: str, node_id: str, payload: SaveInput, session: Session = Depends(get_session)
) -> dict:
    _require_project(session, project_id)
    if payload.storyboard.node_id != node_id:
        raise AppError("node_id 不一致", code="node_id_mismatch", status=400)
    artifact = persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_sb_kind(node_id),
        content=payload.storyboard.model_dump(), prompt_version="", source="user",
        change_reason=payload.change_reason,
    )
    session.commit()
    return _sb_view(Storyboard.model_validate(artifact.content), artifact.version)


@router.post("/projects/{project_id}/storyboard/{node_id}/breakdown")
async def breakdown(
    project_id: str, node_id: str, payload: BreakdownInput, session: Session = Depends(get_session)
) -> dict:
    """AI 拆镜（StoryboardAgent，调用失败回退确定性 mock）并按节点落库。"""
    _require_project(session, project_id)
    await run_storyboard_breakdown(session, project_id, node_id, payload.requested_shots)
    sb, version = _load_storyboard(session, project_id, node_id)
    return _sb_view(sb, version)


@router.post("/projects/{project_id}/storyboard/{node_id}/video")
async def create_video(
    project_id: str, node_id: str, payload: VideoGenInput, session: Session = Depends(get_session)
) -> dict:
    """合成 Seedance 导演提示词 → 提交生视频任务（真实 Seedance / mock 回退）→ 落库 video_job。"""
    _require_project(session, project_id)
    aspect = payload.aspect_ratio if payload.aspect_ratio in ("16:9", "9:16") else "16:9"
    sb, _ = _load_storyboard(session, project_id, node_id)
    if not sb.shots:
        raise AppError(
            "该节点尚无分镜镜头，请先执行「整列拆镜」再生成视频",
            code="storyboard_empty", status=400,
        )
    duration = payload.duration_sec if payload.duration_sec is not None else sum(s.duration_sec for s in sb.shots)
    identity = (sb.metadata or {}).get("character_identity") or ""
    ref_image = (sb.metadata or {}).get("character_ref_image") or None
    prompt = compose_seedance_prompt(sb, character_identity=identity)
    task = await submit_video(
        VideoRequest(prompt=prompt, duration_seconds=int(round(duration)), aspect_ratio=aspect,
                     ref_image=ref_image)
    )

    status: str = "queued"
    video_url = ""
    if task.status == "succeeded":
        result = await poll_video(task.task_id, task)
        status = "done" if not result.error else "failed"
        video_url = result.video_url
    elif task.status == "failed":
        status = "failed"

    job = VideoJob(
        job_id=f"vj-{node_id}-{len(sb.shots)}",
        node_id=node_id,
        status=status,
        duration_sec=round(duration, 2),
        cost_per_second=COST_PER_SECOND,
        total_cost=int(round(duration, 2) * COST_PER_SECOND),
        seedance_director_prompt=prompt,
        task_id=task.task_id,
        video_url=video_url,
        provider=task.provider,
        aspect_ratio=aspect,
    )
    persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_vj_kind(node_id),
        content=job.model_dump(), prompt_version="", source="agent", change_reason="seedance-video",
    )
    session.commit()
    return job.model_dump()


@router.get("/projects/{project_id}/storyboard/{node_id}/video")
async def get_video(project_id: str, node_id: str, session: Session = Depends(get_session)) -> dict:
    """读取 video_job；若仍在排队则向后端厂商轮询一次并回写。"""
    _require_project(session, project_id)
    artifact = latest_artifact(session, project_id, kind=_vj_kind(node_id))
    if artifact is None:
        return {
            "job_id": "", "node_id": node_id, "status": "none", "duration_sec": 0,
            "cost_per_second": COST_PER_SECOND, "total_cost": 0, "seedance_director_prompt": "",
            "task_id": "", "video_url": "", "provider": "mock", "aspect_ratio": "16:9",
        }
    job = VideoJob.model_validate(artifact.content or {"node_id": node_id})
    if job.status == "queued" and job.task_id:
        result = await poll_video(job.task_id)
        if result.status == "succeeded":
            job = job.model_copy(update={"status": "done", "video_url": result.video_url})
        elif result.status == "failed":
            job = job.model_copy(update={"status": "failed"})
        if job.status != "queued":
            persist_versioned_artifact(
                session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_vj_kind(node_id),
                content=job.model_dump(), prompt_version="", source="agent", change_reason="seedance-video-poll",
            )
            session.commit()
    return job.model_dump()