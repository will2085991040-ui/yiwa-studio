"""API 路由：一键生成完整互动剧本（POST /api/projects/{project_id}/script）。

输入一句话创意（goal），用剧本专用模型直接产出并落库一份互动剧本文案（kind="script"）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.services.script_writer import generate_script

router = APIRouter(prefix="/api/projects")


class ScriptGenerateInput(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    genre: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, max_length=120)
    scene_count: int | None = Field(default=None, ge=6, le=120)


@router.post("/{project_id}/script", status_code=201)
async def generate_script_api(
    project_id: str,
    payload: ScriptGenerateInput,
    session: Session = Depends(get_session),
) -> dict:
    result = await generate_script(
        session,
        project_id=project_id,
        goal=payload.goal,
        genre=payload.genre,
        title=payload.title,
        scene_count=payload.scene_count,
    )
    return result
