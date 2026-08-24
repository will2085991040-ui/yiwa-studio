"""API：Skill System（Step 17）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Skill
from app.schemas import SkillCreateInput, SkillOut
from app.services.skills import SkillResolver, skill_registry

router = APIRouter(prefix="/api/projects")


def _skill_out(s: Skill) -> dict:
    return {
        "id": s.id, "name": s.name, "description": s.description, "instructions": s.instructions,
        "version": s.version, "source": s.source, "enabled": s.enabled,
        "priority": s.priority, "forced": s.forced, "is_default": s.is_default,
    }


@router.get("/{project_id}/skills", response_model=list[SkillOut])
def list_skills(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    return [_skill_out(s) for s in SkillResolver(session).resolve(project_id)]


@router.post("/{project_id}/skills", response_model=SkillOut)
def create_skill(
    project_id: str, payload: SkillCreateInput, session: Session = Depends(get_session)
) -> dict:
    skill = skill_registry.create(
        session, project_id,
        name=payload.name, description=payload.description, instructions=payload.instructions,
        source=payload.source, enabled=payload.enabled, priority=payload.priority,
        forced=payload.forced, is_default=payload.is_default,
    )
    return _skill_out(skill)