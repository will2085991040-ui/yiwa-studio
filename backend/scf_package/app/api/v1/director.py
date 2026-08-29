"""API 路由：Director 垂直切片（创意 -> AgentPlan）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.base import get_session
from app.models import AgentSpec, Project
from app.schemas import DirectorPlanOut, DirectorPlanView, GoalInput
from app.services.director_service import create_project_via_director

router = APIRouter(prefix="/api/director")


@router.post("/plan", response_model=DirectorPlanOut, status_code=201)
async def plan(payload: GoalInput, session: Session = Depends(get_session)) -> dict:
    return await create_project_via_director(session, payload.goal, game_type=payload.game_type, title=payload.title)


@router.get("/plan/{project_id}", response_model=DirectorPlanView)
def view_plan(project_id: str, session: Session = Depends(get_session)) -> dict:
    project = session.query(Project).filter(Project.id == project_id).first()
    spec = session.query(AgentSpec).filter(AgentSpec.project_id == project_id).first()
    if project is None or spec is None:
        raise NotFoundError("项目不存在")
    policies = spec.policies or {}
    if "agent_plan" not in policies:
        raise NotFoundError("该项目没有 Director 规划（可能是旧版确定性项目）")
    return {
        "project_id": project_id,
        "goal": project.goal,
        "prompt_version": policies.get("prompt_version", ""),
        "provider": policies.get("provider", ""),
        "model": policies.get("model", ""),
        "agent_plan": policies["agent_plan"],
    }