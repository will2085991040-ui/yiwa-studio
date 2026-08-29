"""API：媒体生成（生图/生视频）——增量：真实 API + mock 回退。

生图：同步返回（mock 立即；SiliconFlow 一次 HTTP）。
生视频：提交→轮询 异步。mock 立即 succeeded；Seedance 走火山方舟内容生成任务。
未配置 key 时自动回退 mock（不报错、不阻塞离线演示）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import get_session
from app.media.images import generate_image
from app.media.types import ImageRequest, VideoRequest
from app.media.video import poll_video, submit_video
from app.models import Project

router = APIRouter(prefix="/api")


class ImageGenInput(BaseModel):
    prompt: str
    negative_prompt: str = ""
    size: str = ""
    n: int = 1
    ref_image: str | None = None


class VideoGenInput(BaseModel):
    prompt: str
    ref_image: str | None = None            # 首帧图
    ref_image_last: str | None = None       # 尾帧图(与 ref_image 一起时走首尾帧)
    duration_seconds: int = 5
    aspect_ratio: str = "16:9"


def _require_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise NotFoundError("项目不存在")


@router.post("/projects/{project_id}/images")
async def generate_project_image(
    project_id: str, payload: ImageGenInput, session: Session = Depends(get_session)
) -> dict:
    _require_project(session, project_id)
    result = await generate_image(ImageRequest(
        prompt=payload.prompt,
        negative_prompt=payload.negative_prompt,
        size=payload.size or "1024x1024",
        n=max(1, payload.n),
        ref_image=payload.ref_image,
    ))
    return result.model_dump()


@router.post("/projects/{project_id}/videos")
async def submit_project_video(
    project_id: str, payload: VideoGenInput, session: Session = Depends(get_session)
) -> dict:
    """提交生视频任务，返回 task_id 供前端轮询。"""
    _require_project(session, project_id)
    task = await submit_video(VideoRequest(
        prompt=payload.prompt,
        ref_image=payload.ref_image,
        ref_image_last=payload.ref_image_last,
        duration_seconds=payload.duration_seconds,
        aspect_ratio=payload.aspect_ratio,
    ))
    return task.model_dump()


@router.get("/projects/{project_id}/videos/{task_id}")
async def poll_project_video(project_id: str, task_id: str, session: Session = Depends(get_session)) -> dict:
    _require_project(session, project_id)
    result = await poll_video(task_id)
    return result.model_dump()