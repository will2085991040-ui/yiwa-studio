"""API：互动影视 HTML 导出（增量：InkOS 互动影游核心 · 干净移植）。"""
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.base import get_session
from app.services.artifacts import latest_artifact
from app.services.if_export import build_playable_html

router = APIRouter(prefix="/api/projects")


@router.get("/{project_id}/storygraph/export.html", response_class=HTMLResponse)
def export_playable_html(project_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    story = latest_artifact(session, project_id, kind="story_graph")
    if story is None or not story.content:
        raise AppError("该项目尚未生成剧情图（StoryGraph）", code="no_story_graph", status=400)
    html = build_playable_html(story.content)
    return HTMLResponse(content=html, media_type="text/html")