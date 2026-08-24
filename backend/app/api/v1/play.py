"""API：Play Runtime（Step 20）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.runtime.play import PlayService
from app.schemas import PlaySessionOut, PlayTurnCreateInput, PlayTurnOut

router = APIRouter(prefix="/api/projects")


@router.post("/{project_id}/play/sessions", response_model=PlaySessionOut)
def create_play_session(project_id: str, session: Session = Depends(get_session)) -> dict:
    return PlayService(session).create(project_id)


@router.get("/{project_id}/play/sessions/{session_id}", response_model=PlaySessionOut)
def get_play_session(project_id: str, session_id: str, session: Session = Depends(get_session)) -> dict:
    return PlayService(session).get(session_id)


@router.get("/{project_id}/play/sessions/{session_id}/world")
def play_world(project_id: str, session_id: str, session: Session = Depends(get_session)) -> dict:
    return PlayService(session).world_view(session_id)


@router.post("/{project_id}/play/sessions/{session_id}/turn", response_model=PlayTurnOut)
def play_turn(
    project_id: str, session_id: str, payload: PlayTurnCreateInput, session: Session = Depends(get_session)
) -> dict:
    return PlayService(session).turn(session_id, intent=payload.intent, mutation=payload.mutation)