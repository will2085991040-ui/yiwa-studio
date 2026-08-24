"""API：Interactive Creation Layer（Step 8）—— 用户修改 / 局部执行 / 版本历史；Step 10 增加剧情操作。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Artifact
from app.schemas import (
    ArtifactCompareInput,
    ArtifactCompareOut,
    ArtifactGovernanceOut,
    ArtifactOut,
    ArtifactVersionInput,
    DialogueOperationInput,
    OrchestrationOut,
    RevisionInput,
    SceneOperationInput,
    StoryOperationInput,
)
from app.services.dialogue_service import run_dialogue_operation
from app.services.governance import compare_artifacts, promote_artifact, revert_artifact
from app.services.manual_edit import edit_artifact_content
from app.services.revision import rerun_task, revise_artifact
from app.services.scene_service import run_scene_operation
from app.services.story_ops import add_branch, extend_story

router = APIRouter(prefix="/api/projects")


class ManualEditInput(BaseModel):
    """手动编辑任意已生成内容：kind + 完整 content + 可选修改说明。"""

    kind: str
    content: dict
    change_reason: str | None = None


@router.post("/{project_id}/revise", response_model=OrchestrationOut)
async def revise_artifact_endpoint(
    project_id: str, payload: RevisionInput, session: Session = Depends(get_session)
) -> dict:
    return await revise_artifact(session, project_id, kind=payload.kind, instruction=payload.instruction)


@router.post("/{project_id}/tasks/{task_id}/run", response_model=OrchestrationOut)
async def run_task_endpoint(project_id: str, task_id: str, session: Session = Depends(get_session)) -> dict:
    return await rerun_task(session, project_id, task_id)


@router.post("/{project_id}/story", response_model=OrchestrationOut)
def story_operation_endpoint(
    project_id: str, payload: StoryOperationInput, session: Session = Depends(get_session)
) -> dict:
    """剧情结构操作：extend（延长）/ branch（增加分支）。确定性图算法，产出 story_graph v+1。"""
    if payload.operation == "extend":
        return extend_story(session, project_id, instruction=payload.instruction, count=payload.count)
    return add_branch(session, project_id, instruction=payload.instruction, anchor_node_id=payload.anchor_node_id)


@router.post("/{project_id}/scene", response_model=OrchestrationOut)
async def scene_operation_endpoint(
    project_id: str, payload: SceneOperationInput, session: Session = Depends(get_session)
) -> dict:
    """场景局部操作：generate（生成）/ revise（修改）/ expand（扩写）单个 SceneNode，产出 scene:{node_id} v+1。"""
    return await run_scene_operation(
        session, project_id, operation=payload.operation, node_id=payload.node_id, instruction=payload.instruction
    )


@router.post("/{project_id}/dialogue", response_model=OrchestrationOut)
async def dialogue_operation_endpoint(
    project_id: str, payload: DialogueOperationInput, session: Session = Depends(get_session)
) -> dict:
    """对白局部操作：generate（生成）/ revise（修改）/ expand（扩写）单个 (node_id, choice_id)，
    产出 dialogue:{node_id} 或 dialogue:{node_id}:{choice_id} 的版本化 Artifact。"""
    return await run_dialogue_operation(
        session,
        project_id,
        operation=payload.operation,
        node_id=payload.node_id,
        choice_id=payload.choice_id,
        instruction=payload.instruction,
    )


@router.put("/{project_id}/artifacts/content", response_model=OrchestrationOut)
def manual_edit_artifact(
    project_id: str, payload: ManualEditInput, session: Session = Depends(get_session)
) -> dict:
    """手动编辑任意已生成内容（schema 校验 + source=user 新版本落库）。"""
    return edit_artifact_content(
        session, project_id, kind=payload.kind,
        content=payload.content, change_reason=payload.change_reason,
    )


@router.get("/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_artifact_history(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    """完整版本历史（含被替换的旧版本，Git 式查看）。"""
    artifacts = (
        session.query(Artifact)
        .filter(Artifact.project_id == project_id)
        .order_by(Artifact.kind, Artifact.version)
        .all()
    )
    return [_artifact_dict(a) for a in artifacts]


@router.post("/{project_id}/artifacts/compare", response_model=ArtifactCompareOut)
def compare_artifact_versions(
    project_id: str, payload: ArtifactCompareInput, session: Session = Depends(get_session)
) -> dict:
    """对比同 kind 两个版本的内容与元数据差异（确定性 diff）。"""
    return compare_artifacts(
        session, project_id=project_id, kind=payload.kind,
        version_a=payload.version_a, version_b=payload.version_b,
    )


@router.post("/{project_id}/artifacts/promote", response_model=ArtifactGovernanceOut)
def promote_artifact_version(
    project_id: str, payload: ArtifactVersionInput, session: Session = Depends(get_session)
) -> dict:
    """把指定历史版本设为当前 latest；历史全部保留，且保证唯一 latest。"""
    return promote_artifact(
        session, project_id=project_id, kind=payload.kind,
        version=payload.version, expected_latest=payload.expected_latest,
    )


@router.post("/{project_id}/artifacts/revert", response_model=ArtifactGovernanceOut)
def revert_artifact_version(
    project_id: str, payload: ArtifactVersionInput, session: Session = Depends(get_session)
) -> dict:
    """回滚 = 追加新版本（content 取自旧版本，parent 指向当前 latest），不物理删除历史。"""
    return revert_artifact(
        session, project_id=project_id, kind=payload.kind,
        version=payload.version, expected_latest=payload.expected_latest,
    )


def _artifact_dict(a: Artifact) -> dict:
    return {
        "id": a.id, "task_id": a.task_id, "agent": a.agent, "kind": a.kind,
        "content": a.content or {}, "prompt_version": a.prompt_version,
        "version": a.version, "parent_version": a.parent_version,
        "source": a.source, "change_reason": a.change_reason, "is_latest": a.is_latest,
    }