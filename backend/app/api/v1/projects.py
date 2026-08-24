"""API 路由：Golden Path Phase 0 端点（全部真实读写数据库）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents.base import registry
from app.core.config import settings
from app.core.errors import NotFoundError
from app.db.base import get_session
from app.llm.provider import provider_status
from app.models import AgentRun, AgentSpec, Project
from app.runtime.service import runtime
from app.schemas import (
    AgentCreated,
    AgentDefinition,
    AgentRunOut,
    ChatInput,
    ChatOut,
    GoalInput,
    HealthOut,
    PlanStep,
    ProjectOut,
    WorkflowOut,
)
from app.services.agent_factory import create_agent_from_goal

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    ps = provider_status()
    return HealthOut(
        status="ok",
        version="0.1.0-phase0",
        llm_provider=settings.llm_provider,
        agents_registered=len(registry.list()),
        llm_mode=ps["mode"],
        llm_fallback=ps["fallback"],
        llm_note=ps["note"],
    )


@router.get("/agents", response_model=list[AgentDefinition])
def list_agents() -> list[dict]:
    return registry.list()


@router.post("/projects", response_model=AgentCreated, status_code=201)
def create_agent(payload: GoalInput, session: Session = Depends(get_session)) -> dict:
    """Golden Path 入口：自然语言目标 → Project + AgentSpec v1 + AgentVersion v1。"""
    return create_agent_from_goal(session, payload.goal)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return session.query(Project).order_by(Project.created_at.desc()).all()


def _spec_of(session: Session, project_id: str) -> AgentSpec:
    spec = session.query(AgentSpec).filter(AgentSpec.project_id == project_id).first()
    if spec is None:
        raise NotFoundError("Agent 不存在")
    return spec


@router.get("/projects/{project_id}/workflow", response_model=WorkflowOut)
def workflow(project_id: str, session: Session = Depends(get_session)) -> dict:
    spec = _spec_of(session, project_id)
    return {
        "project_id": project_id,
        "status": spec.status,
        "steps": [PlanStep(**s) for s in (spec.plan or [])],
    }


@router.post("/projects/{project_id}/chat", response_model=ChatOut)
async def chat(project_id: str, payload: ChatInput, session: Session = Depends(get_session)) -> dict:
    spec = _spec_of(session, project_id)
    return await runtime.handle(session, spec.id, payload.message)


@router.get("/projects/{project_id}/traces", response_model=list[AgentRunOut])
def traces(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    spec = _spec_of(session, project_id)
    version_ids = [v.id for v in spec.versions]
    runs = (
        session.query(AgentRun)
        .filter(AgentRun.agent_version_id.in_(version_ids))
        .order_by(AgentRun.started_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "started_at": r.started_at,
            "steps": [
                {
                    "id": s.id,
                    "seq": s.seq,
                    "agent": s.agent,
                    "step_key": s.step_key,
                    "status": s.status,
                    "latency_ms": s.latency_ms,
                    "token_usage": s.token_usage or {},
                    "error": s.error,
                }
                for s in sorted(r.steps, key=lambda x: x.seq)
            ],
        }
        for r in runs
    ]
