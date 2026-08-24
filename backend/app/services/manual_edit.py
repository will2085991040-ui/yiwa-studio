"""Artifact 手动编辑（Step 22）：让用户对已生成的内容做「手动增删改」。

核心 UX 约束：生成的东西必须能改。此服务把任意 versioned Artifact 的 content
作为新版本落库（source=user，Git 式追加，旧版本保留），并在 know 的 schema 上做校验，
保证手动编辑不破坏结构（storygraph/世界观/关系图/角色卡/分镜）。

编辑 kind 通过 body 传入（含 scene:{node_id} / character_card:{id} 这类带冒号的 kind）。
"""
from pydantic import ValidationError

from app.core.errors import AppError, NotFoundError
from app.models import Project
from app.schemas.character_card import CharacterCard
from app.schemas.relationship_graph import RelationshipGraph
from app.schemas.story_graph import StoryGraph
from app.schemas.storyboard import Storyboard
from app.schemas.world_bible import WorldBible
from app.services.artifacts import persist_versioned_artifact
from app.services.orchestrator import read_orchestration

# base 前缀 -> 校验 Schema（带冒号的 kind 取其前缀）
_EDITABLE_BY_SCHEMA = {
    "world_bible": WorldBible,
    "relationship_graph": RelationshipGraph,
    "story_graph": StoryGraph,
    "character_card": CharacterCard,
    "storyboard": Storyboard,
}


def _validation_message(exc: ValidationError) -> str:
    return "；".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])


def edit_artifact_content(
    session, project_id: str, *, kind: str, content: dict, change_reason: str | None = None
) -> dict:
    """把用户手写给定的 kind 内容作为新版本落库，返回 Orchestration 快照。"""
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    if not (kind or "").strip():
        raise AppError("缺少 kind（要被编辑的内容类型）", code="kind_required", status=400)

    base = kind.split(":", 1)[0]
    model = _EDITABLE_BY_SCHEMA.get(base)
    if model is not None:
        try:
            content = model.model_validate(content or {}).model_dump()
        except ValidationError as exc:
            raise AppError(
                f"手动编辑的内容不符合 {kind} 的结构：{_validation_message(exc)}",
                code="invalid_content", status=422,
            ) from exc
    else:
        # plot / scene:{node_id} 等编辑器人工维护的 kind：接受任意 JSON 对象
        content = dict(content or {})

    if kind.startswith("scene:"):
        content["scene_id"] = kind.split(":", 1)[1]  # 稳定引用：scene_id 恒等于 node_id

    persist_versioned_artifact(
        session, project_id=project_id, task_id=f"manual-{kind}",
        agent="user_editor", kind=kind, content=content, prompt_version="",
        source="user", change_reason=change_reason or "手动编辑",
    )
    project.current_version += 1
    session.commit()
    return read_orchestration(session, project_id)