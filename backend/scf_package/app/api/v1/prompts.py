"""API 路由：Prompt 版本基础设施（定义 + 不可变版本 + 变量渲染）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.base import get_session
from app.models import PromptDefinition
from app.schemas import (
    PromptDefinitionCreate,
    PromptDefinitionOut,
    PromptRenderInput,
    PromptRenderOut,
    PromptVersionCreate,
    PromptVersionOut,
)
from app.services.prompts import (
    create_version,
    get_definition,
    get_or_create_definition,
    get_version,
    list_definitions,
    list_versions,
    render,
)

router = APIRouter(prefix="/api/prompts")


def _definition_out(definition: PromptDefinition) -> dict:
    return {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "created_at": definition.created_at,
    }


def _version_out(version) -> dict:
    return {
        "id": version.id,
        "prompt_definition_id": version.prompt_definition_id,
        "version_no": version.version_no,
        "content": version.content,
        "variables": version.variables or [],
        "model_preferences": version.model_preferences or {},
        "status": version.status,
        "created_at": version.created_at,
    }


def _definition(session: Session, name: str) -> PromptDefinition:
    definition = get_definition(session, name)
    if definition is None:
        raise NotFoundError(f"Prompt 定义 '{name}' 不存在")
    return definition


@router.get("/definitions", response_model=list[PromptDefinitionOut])
def list_all_definitions(session: Session = Depends(get_session)) -> list[dict]:
    return [_definition_out(d) for d in list_definitions(session)]


@router.post("/definitions", response_model=PromptDefinitionOut)
def create_or_get_definition(payload: PromptDefinitionCreate, session: Session = Depends(get_session)) -> dict:
    """幂等地获取或创建 Prompt 定义（name 为稳定引用键）。"""
    definition = get_or_create_definition(session, payload.name, payload.description)
    return _definition_out(definition)


@router.post("/definitions/{name}/versions", response_model=PromptVersionOut, status_code=201)
def add_version(name: str, payload: PromptVersionCreate, session: Session = Depends(get_session)) -> dict:
    """追加新版本（v1/v2...自增）；旧版本不可原地修改。"""
    definition = _definition(session, name)
    version = create_version(
        session,
        definition,
        content=payload.content,
        variables=[v.model_dump() for v in payload.variables],
        model_preferences=payload.model_preferences,
        status=payload.status,
    )
    return _version_out(version)


@router.get("/definitions/{name}/versions", response_model=list[PromptVersionOut])
def versions_of(name: str, session: Session = Depends(get_session)) -> list[dict]:
    definition = _definition(session, name)
    return [_version_out(v) for v in list_versions(session, definition)]


@router.get("/definitions/{name}/versions/{version_no}", response_model=PromptVersionOut)
def one_version(name: str, version_no: int, session: Session = Depends(get_session)) -> dict:
    definition = _definition(session, name)
    version = get_version(session, definition, version_no)
    if version is None:
        raise NotFoundError(f"Prompt '{name}' v{version_no} 不存在")
    return _version_out(version)


@router.post("/definitions/{name}/versions/{version_no}/render", response_model=PromptRenderOut)
def render_version(
    name: str,
    version_no: int,
    payload: PromptRenderInput,
    session: Session = Depends(get_session),
) -> PromptRenderOut:
    definition = _definition(session, name)
    version = get_version(session, definition, version_no)
    if version is None:
        raise NotFoundError(f"Prompt '{name}' v{version_no} 不存在")
    try:
        rendered = render(version, payload.variables)
    except ValueError as exc:
        raise AppError(str(exc), code="missing_variable", status=400) from exc
    return PromptRenderOut(
        prompt_id=name,
        prompt_version=version_no,
        rendered=rendered,
        used_variables=payload.variables,
    )