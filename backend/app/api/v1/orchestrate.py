"""API：Orchestrator 执行入口（读取 AgentPlan -> DAG 调度 -> WorldBible Artifact）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.schemas import OrchestrationOut
from app.services.orchestrator import orchestrate_project, read_orchestration

router = APIRouter(prefix="/api/orchestrate")


@router.post("/{project_id}", response_model=OrchestrationOut)
async def run_orchestration(project_id: str, session: Session = Depends(get_session)) -> dict:
    return await orchestrate_project(session, project_id)


@router.get("/{project_id}", response_model=OrchestrationOut)
def get_orchestration(project_id: str, session: Session = Depends(get_session)) -> dict:
    return read_orchestration(session, project_id)