"""API: 资产（Assets）——各 Agent 产出汇总为资产列表。

GET /api/assets                : 全部项目的最新资产
GET /api/projects/{id}/assets : 指定项目的最新资产
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Artifact, Project

router = APIRouter()

_LABEL = {
    "story_graph": "剧本", "story": "故事大纲", "world": "世界观", "world_bible": "世界观",
    "character_card": "角色卡", "character_portrait": "角色立绘",
    "node_image": "节点画面", "storyboard": "分镜", "video_job": "视频", "scene": "场景",
    "dialogue": "对白", "choice": "选择", "ending": "结局",
    "relationship_graph": "关系图", "image": "图片", "audio": "音频",
}
_TEXT = {"story_graph", "story", "world", "world_bible", "character_card", "scene",
         "dialogue", "relationship_graph", "plot", "branch", "ending", "choice"}

_URL_KEYS = ("video_url", "url", "image_url", "download_url", "signed_url", "audio_url", "file_url")


def _clean(s):
    s = (s or "").strip()
    if s.startswith(("http://", "https://", "data:", "mock://", "file://", "blob:")):
        if s.startswith("data:image") and len(s) > 1_100_000:
            s = s[:1_100_000]
        return s
    return ""


def _url(value, depth=0):
    if depth > 8:
        return ""
    if isinstance(value, str):
        return _clean(value)
    if isinstance(value, dict):
        for k in _URL_KEYS:
            v = value.get(k)
            if isinstance(v, str) and _clean(v):
                return _clean(v)
        for k in ("urls", "images", "videos", "results", "items"):
            v = value.get(k)
            if isinstance(v, list):
                for it in v:
                    u = _url(it, depth + 1)
                    if u:
                        return u
        for k in ("content", "image", "video", "variant", "file", "thumbnail"):
            if k in value:
                u = _url(value[k], depth + 1)
                if u:
                    return u
    elif isinstance(value, list | tuple):
        for it in value:
            u = _url(it, depth + 1)
            if u:
                return u
    return ""


def _label(kind):
    base = kind.split(":")[0]
    return _LABEL.get(base, base)


def _title(kind, cnt):
    if isinstance(cnt, dict):
        for k in ("title", "name", "character_name", "caption", "summary", "prompt"):
            v = cnt.get(k)
            if isinstance(v, str) and v.strip():
                t = v.strip().replace("\n", " ")
                return t[:80]
    return _label(kind)


def _type(kind, cnt):
    base = kind.split(":")[0]
    if base in ("video", "video_job"):
        return "video"
    if base in ("video", "video_job"):
        return "video"
    if base in ("character_portrait", "portrait", "node_image", "image"):
        return "image"
    raw = str(cnt)[:2000]
    if "data:image" in raw:
        return "image"
    if base in _TEXT:
        return "text"
    return "other"


def _build(proj_titles, arts):
    out = []
    for a in arts:
        try:
            cnt = a.content or {}
        except Exception:
            cnt = {}
        out.append({
            "id": a.id, "project_id": a.project_id,
            "project_title": proj_titles.get(a.project_id, ""),
            "agent": a.agent, "kind": a.kind, "kind_label": _label(a.kind),
            "type": _type(a.kind, cnt), "title": _title(a.kind, cnt),
            "version": a.version, "url": _url(cnt), "is_latest": a.is_latest,
            "source": a.source, "created_at": (a.created_at.isoformat() if a.created_at else ""),
        })
    order = {"video": 0, "image": 1, "text": 2, "other": 3}
    out.sort(key=lambda x: (order.get(x["type"], 9), x["created_at"] or ""), )
    return out


@router.get("/api/assets")
def list_all_assets(session: Session = Depends(get_session)):
    projs = {p.id: p.title for p in session.query(Project).all()}
    arts = (
        session.query(Artifact).filter(Artifact.is_latest.is_(True))
        .order_by(Artifact.created_at.desc()).all()
    )
    return _build(projs, arts)


@router.get("/api/projects/{project_id}/assets")
def list_project_assets(project_id: str, session: Session = Depends(get_session)):
    projs = {p.id: p.title for p in session.query(Project).filter(Project.id == project_id).all()}
    arts = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id, Artifact.is_latest.is_(True))
        .order_by(Artifact.created_at.desc()).all()
    )
    return _build(projs, arts)
