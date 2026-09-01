"""API：分镜拆镜 + 视频生成（增量：Funloom 蒸馏 · Phase 3）。

权威数据 = Artifact(kind="storyboard:{node_id}") 与 Artifact(kind="video_job:{node_id}")，
复用既有 versioned artifact 链。视频生成为确定性 mock（离线计价 + 状态），不冒充真实渲染。
"""
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.media.compose import compose_clips
from app.media.images import generate_image
from app.media.types import ImageRequest, VideoRequest
from app.media.video import poll_video, submit_video
from app.models import Artifact, Project
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


def _clips_kind(node_id: str) -> str:
    return f"video_clips:{node_id}"


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
    ref_image: str | None = None   # 首帧图（可用小画布刚生成的图保证人物一致）
    ref_image_last: str | None = None   # 尾帧图（与 ref_image 一起时用首尾帧控制起止画面）
    resolution: str = "768P"      # 视频分辨率：4802P/720P/768P/1080P/2K/4K（MiniMax 建议 768P）
    style: str = ""               # 画面风格 key

    @property
    def eff_duration(self) -> int:
        """生成时长：允许 4~15s，缺省取镜头合计与 5s 的折衷（≥5）。"""
        raw = float(self.duration_sec or 5)
        return max(4, min(15, int(round(raw))))


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
    duration = max(1, min(15, int(round(float(duration)))))
    identity = (sb.metadata or {}).get("character_identity") or ""
    ref_image = (sb.metadata or {}).get("character_ref_image") or payload.ref_image or None
    prompt = compose_seedance_prompt(sb, character_identity=identity)
    task = await submit_video(
        VideoRequest(prompt=prompt, duration_seconds=duration, aspect_ratio=aspect,
                     ref_image=ref_image, ref_image_last=payload.ref_image_last, style=payload.style or ""),
        resolution=payload.resolution,
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
            job = job.model_copy(update={"status": "failed", "error": result.error or "视频生成失败（厂商未返回具体原因）"})
        if job.status != "queued":
            persist_versioned_artifact(
                session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_vj_kind(node_id),
                content=job.model_dump(), prompt_version="", source="agent", change_reason="seedance-video-poll",
            )
            session.commit()
    return job.model_dump()


def _resolution(r: str = "") -> str:
    """归一化视频分辨率到 MiniMax 接受的值（默认 768P）。"""
    norm = (r or "").strip().lower().replace("p", "")
    table = {"480": "480P", "4802": "4802P", "540": "720P", "720": "720P", "768": "768P",
             "1080": "1080P", "2k": "2K", "4k": "4K"}
    return table.get(norm, "")


def _clip_cost(n: int, per_sec: float = 5.0) -> int:
    """n 个镜头，每镜头按 per_sec 时长计价（10 积分/秒）。"""
    return int(round(per_sec * COST_PER_SECOND * n))


@router.post("/projects/{project_id}/storyboard/{node_id}/video/clips")
async def create_clips(
    project_id: str, node_id: str, payload: VideoGenInput, session: Session = Depends(get_session)
) -> dict:
    """按分镜逐个生成镜头视频（每镜头一个厂商 task），落库 video_clips。"""
    _require_project(session, project_id)
    dur = payload.eff_duration
    aspect = payload.aspect_ratio if payload.aspect_ratio in ("16:9", "9:16") else "16:9"
    resolution = _resolution(payload.resolution)
    sb, _ = _load_storyboard(session, project_id, node_id)
    if not sb.shots:
        raise AppError("该节点尚无分镜镜头，请先执行「整列拆镜」再生成视频", code="storyboard_empty", status=400)
    identity = (sb.metadata or {}).get("character_identity") or ""
    ref_image = (sb.metadata or {}).get("character_ref_image") or payload.ref_image or None

    clips: list[dict] = []
    for shot in sb.shots:
        prompt = compose_shot_prompt(shot, character_identity=identity)
        item: dict = {"shot_no": shot.shot_no, "prompt": prompt, "status": "queued",
                      "task_id": "", "provider": "mock", "model": "", "video_url": "", "error": ""}
        try:
            task = await submit_video(VideoRequest(
                prompt=prompt, duration_seconds=dur, aspect_ratio=aspect, ref_image=ref_image,
                ref_image_last=payload.ref_image_last, style=payload.style or ""), resolution=payload.resolution)
            item["task_id"] = task.task_id
            item["provider"] = task.provider
            item["model"] = task.model
            item["status"] = task.status
            if task.status == "succeeded":
                item["status"] = "done"
                item["video_url"] = f"mock://video/{task.task_id}.mp4"
        except Exception as exc:  # 单个镜头失败不阻断整批
            item["status"] = "failed"
            item["error"] = str(exc)[:400]
        clips.append(item)

    doc: dict = {"node_id": node_id, "aspect_ratio": aspect, "duration_per_clip": dur,
                 "resolution": res, "cost_per_second": COST_PER_SECOND, "total_cost": _clip_cost(len(clips), dur),
                 "clips": clips, "status": "running"}
    persist_versioned_artifact(
        session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_clips_kind(node_id),
        content=doc, prompt_version="", source="agent", change_reason="per-shot-video-clips",
    )
    session.commit()
    return doc


@router.get("/projects/{project_id}/storyboard/{node_id}/video/clips")
async def get_clips(project_id: str, node_id: str, session: Session = Depends(get_session)) -> dict:
    """读取 video_clips；对仍在排队的镜头逐个向厂商轮询一次并回写。"""
    _require_project(session, project_id)
    artifact = latest_artifact(session, project_id, kind=_clips_kind(node_id))
    if artifact is None or not (artifact.content or {}).get("clips"):
        return {"node_id": node_id, "status": "none", "clips": [], "total_cost": 0,
                "duration_per_clip": 5, "cost_per_second": COST_PER_SECOND}
    doc = dict(artifact.content)
    clips: list[dict] = list(doc.get("clips", []))
    changed = False
    for item in clips:
        if item.get("status") == "queued" and item.get("task_id"):
            try:
                result = await poll_video(item["task_id"], task=None)
                if result.status == "succeeded":
                    item["status"] = "done"
                    item["video_url"] = result.video_url
                elif result.status == "failed":
                    item["status"] = "failed"
                    item["error"] = result.error or "镜头生成失败（厂商未返回具体原因）"
                changed = True
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)[:300]
                changed = True
    if changed:
        doc = {**doc, "clips": clips}
        persist_versioned_artifact(
            session, project_id=project_id, task_id=_TASK, agent=_AGENT, kind=_clips_kind(node_id),
            content=doc, prompt_version="", source="agent", change_reason="video-clips-poll",
        )
        session.commit()
    done = sum(1 for c in clips if c.get("status") == "done")
    doc = {**doc, "clips": clips, "total_cost": _clip_cost(len(clips))}
    doc["status"] = "done" if done == len(clips) and clips else ("running" if clips else "none")
    return doc


def _compose_dir(project_id: str) -> Path:
    if settings.yiwa_data_dir:
        base = Path(settings.yiwa_data_dir)
    else:
        base = Path(os.environ.get("APPDATA", Path.home())) / "YIWA" / "data"
    d = base / "composes" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class ComposeInput(BaseModel):
    order: list[int] = []          # 合成顺序：镜头 shot_no 列表（缺省按 storyboard 顺序）
    transition: str = "hard"       # hard(硬切) / fade(淡入淡出)
    filename: str = "成片"


@router.post("/projects/{project_id}/storyboard/{node_id}/video/clips/compose")
async def compose_film(
    project_id: str, node_id: str, payload: ComposeInput, session: Session = Depends(get_session)
) -> dict:
    """把已生成的各镜头片段按序合成一个完整 mp4（ffmpeg concat），返回可下载地址。"""
    _require_project(session, project_id)
    artifact = latest_artifact(session, project_id, kind=_clips_kind(node_id))
    if artifact is None or not (artifact.content or {}).get("clips"):
        raise AppError("请先生成逐个镜头", code="clips_empty", status=400)
    clips: list[dict] = list((artifact.content or {}).get("clips", []))

    order = payload.order or []
    if order:
        by_no = {str(c.get("shot_no")): c for c in clips}
        missing = [o for o in order if o not in by_no]
        if missing:
            raise AppError("存在未识别的镜头序号: " + ",".join(map(str, missing)), status=400)
        ordered = [by_no[o] for o in order]
    else:
        ordered = sorted(clips, key=lambda c: int(c.get("shot_no") or 0))

    done = [c for c in ordered if c.get("status") == "done" and c.get("video_url")]
    if len(done) < len(ordered):
        notdone = [c.get("shot_no") for c in ordered if c.get("status") != "done" or not c.get("video_url")]
        raise AppError("以下镜头尚未生成完成: " + ",".join(map(str, notdone)), status=400)

    out_dir = _compose_dir(project_id)
    safe = re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", payload.filename or "成片")[:40] or "成片"
    out = out_dir / f"{safe}-{uuid.uuid4().hex[:6]}.mp4"
    try:
        await compose_clips([c["video_url"] for c in done], out, transition=payload.transition)
    except Exception as exc:
        raise AppError("视频合成失败: " + str(exc), status=500)
    return {"url": f"/api/projects/{project_id}/compose/{out.name}",
            "filename": out.name, "size": out.stat().st_size if out.exists() else 0,
            "clips": len(done), "transition": payload.transition}


@router.get("/projects/{project_id}/compose/{filename}")
async def download_compose(project_id: str, filename: str) -> FileResponse:
    out = _compose_dir(project_id) / filename
    if not out.exists() or not out.is_file():
        raise NotFoundError("成片不存在")
    return FileResponse(out, media_type="video/mp4", filename=filename)


class NodeImageInput(BaseModel):
    prompt: str
    style: str = ""
    aspect: str = "9:16"
    ref_image: str | None = None


def _node_img_kind(node_id: str) -> str:
    return "node_image:" + node_id


def _node_aspect_size(aspect: str) -> str:
    if aspect == "9:16":
        return "768x1344"
    if aspect == "16:9":
        return "1344x768"
    return "1024x1024"


@router.post("/projects/{project_id}/nodes/{node_id}/images")
async def create_node_image(
    project_id: str, node_id: str, payload: NodeImageInput, session: Session = Depends(get_session),
) -> dict:
    """小画布：为指定剧情节点点生成画面（style），并持久化为节点资产。"""
    _require_project(session, project_id)
    result = await generate_image(ImageRequest(
        prompt=payload.prompt, style=payload.style,
        size=_node_aspect_size(payload.aspect), ref_image=payload.ref_image,
    ))
    url = result.urls[0] if result.urls else (result.b64[0] if result.b64 else "")
    content = {
        "node_id": node_id, "url": url, "provider": result.provider, "model": result.model,
        "prompt": payload.prompt, "style": payload.style, "aspect": payload.aspect,
        "ref_image": payload.ref_image,
    }
    persist_versioned_artifact(
        session, project_id=project_id, task_id="node-image-" + node_id, agent=_AGENT,
        kind=_node_img_kind(node_id), content=content, prompt_version="", source="generated",
        change_reason="canvas-node-image",
    )
    session.commit()
    return content


@router.get("/projects/{project_id}/nodes/{node_id}/canvas")
def get_node_canvas(project_id: str, node_id: str, session: Session = Depends(get_session)) -> dict:
    """分节点小画布：该节点分镜 + 已生成图 + 视频 + 风格列表，一次性灌给前端。"""
    _require_project(session, project_id)
    sb, sb_ver = _load_storyboard(session, project_id, node_id)
    rows = (
        session.query(Artifact).filter(
            Artifact.project_id == project_id, Artifact.kind == _node_img_kind(node_id),
        ).order_by(Artifact.created_at.desc()).all()
    )
    images = [
        {k: (a.content or {}).get(k) for k in ("url", "prompt", "style", "aspect")}
        for a in rows
    ]
    video = latest_artifact(session, project_id, kind=_vj_kind(node_id))
    from app.media.styles import style_catalog
    # 小画布通用时 style 用 key/label 契约（与 style_catalog 的 id/label 对齐映射）
    styles = [{"key": s["id"], "label": s["label"]} for s in style_catalog()]
    return {
        "node_id": node_id,
        "storyboard": _sb_view(sb, sb_ver),
        "images": images,
        "video": (VideoJob.model_validate(video.content).model_dump() if video and video.content else None),
        "styles": styles,
    }