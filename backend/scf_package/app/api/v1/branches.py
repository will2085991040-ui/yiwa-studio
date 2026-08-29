"""API：Branch（Step 18）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.models import Branch, BranchVersion
from app.schemas import (
    BranchCompareInput,
    BranchCompareOut,
    BranchCreateInput,
    BranchMergeInput,
    BranchOut,
    BranchSnapshotInput,
    BranchVersionOut,
)
from app.services.branch import BranchService

router = APIRouter(prefix="/api/projects")


def _branch_out(b: Branch) -> dict:
    return {
        "id": b.id, "project_id": b.project_id, "parent_branch_id": b.parent_branch_id,
        "name": b.name, "description": b.description, "status": b.status,
        "base_version": b.base_version, "base_kind": b.base_kind,
        "current_node_id": b.current_node_id, "state": b.state or {}, "is_selected": b.is_selected,
    }


def _version_out(v: BranchVersion) -> dict:
    return {
        "id": v.id, "branch_id": v.branch_id, "version_no": v.version_no,
        "kind": v.kind, "content": v.content or {}, "change_reason": v.change_reason,
    }


@router.get("/{project_id}/branches", response_model=list[BranchOut])
def list_branches(project_id: str, session: Session = Depends(get_session)) -> list[dict]:
    return [_branch_out(b) for b in BranchService(session).list_branches(project_id)]


@router.get("/{project_id}/branches/current", response_model=BranchOut | None)
def current_branch(project_id: str, session: Session = Depends(get_session)):
    b = BranchService(session).current(project_id)
    return _branch_out(b) if b else None


@router.post("/{project_id}/branches", response_model=BranchOut)
def create_branch(project_id: str, payload: BranchCreateInput, session: Session = Depends(get_session)) -> dict:
    b = BranchService(session).create(
        project_id, name=payload.name, description=payload.description, plan=payload.plan,
        base_version=payload.base_version, parent_branch_id=payload.parent_branch_id,
        current_node_id=payload.current_node_id, state=payload.state,
    )
    return _branch_out(b)


@router.post("/{project_id}/branches/compare", response_model=BranchCompareOut)
def compare_branches(project_id: str, payload: BranchCompareInput, session: Session = Depends(get_session)) -> dict:
    return BranchService(session).compare(payload.branch_a_id, payload.branch_b_id)


@router.post("/{project_id}/branches/{branch_id}/switch", response_model=BranchOut)
def switch_branch(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> dict:
    return _branch_out(BranchService(session).switch(project_id, branch_id))


@router.post("/{project_id}/branches/{branch_id}/copy", response_model=BranchOut)
def copy_branch(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> dict:
    return _branch_out(BranchService(session).copy(branch_id))


@router.post("/{project_id}/branches/{branch_id}/abandon", response_model=BranchOut)
def abandon_branch(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> dict:
    return _branch_out(BranchService(session).abandon(branch_id))


@router.post("/{project_id}/branches/{branch_id}/restore", response_model=BranchOut)
def restore_branch(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> dict:
    return _branch_out(BranchService(session).restore(branch_id))


@router.post("/{project_id}/branches/{branch_id}/snapshot", response_model=BranchVersionOut)
def snapshot_branch(
    project_id: str, branch_id: str, payload: BranchSnapshotInput, session: Session = Depends(get_session)
) -> dict:
    return _version_out(
        BranchService(session).snapshot(branch_id, payload.content, change_reason=payload.change_reason),
    )


@router.get("/{project_id}/branches/{branch_id}/versions", response_model=list[BranchVersionOut])
def branch_versions(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> list[dict]:
    return [_version_out(v) for v in BranchService(session).versions(branch_id)]


@router.post("/{project_id}/branches/{branch_id}/merge", response_model=BranchOut)
def merge_branch(
    project_id: str, branch_id: str, payload: BranchMergeInput, session: Session = Depends(get_session)
) -> dict:
    return _branch_out(BranchService(session).merge(branch_id, payload.target_branch_id))


@router.get("/{project_id}/branches/{branch_id}/ending")
def branch_ending(project_id: str, branch_id: str, session: Session = Depends(get_session)) -> dict:
    return {"is_ending": BranchService(session).is_ending(branch_id)}