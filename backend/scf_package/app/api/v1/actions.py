"""API：Creative Action + HITL（Step 16）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.schemas import ActionOut, CreativeActionInput
from app.services.actions import ActionExecution, CreativeAction

router = APIRouter(prefix="/api/projects")


@router.post("/{project_id}/actions", response_model=ActionOut)
def submit_action(
    project_id: str, payload: CreativeActionInput, session: Session = Depends(get_session)
) -> dict:
    action = CreativeAction(
        operation=payload.operation, source=payload.source, kind=payload.kind,
        payload=payload.payload, node_id=payload.node_id, choice_id=payload.choice_id,
    )
    return ActionExecution(session).execute(project_id, action)


@router.post("/{project_id}/actions/proposals/{proposal_id}/confirm", response_model=ActionOut)
def confirm_proposal(project_id: str, proposal_id: str, session: Session = Depends(get_session)) -> dict:
    return ActionExecution(session).confirm(proposal_id, approve=True)


@router.post("/{project_id}/actions/proposals/{proposal_id}/reject", response_model=ActionOut)
def reject_proposal(project_id: str, proposal_id: str, session: Session = Depends(get_session)) -> dict:
    return ActionExecution(session).reject(proposal_id)