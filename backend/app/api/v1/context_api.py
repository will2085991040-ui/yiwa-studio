"""API：Unified Context Compiler（Step 15）—— 统一上下文装配的单一路口。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.schemas import ContextCompileInput, ContextCompileOut
from app.services.context_compiler import compile_context

router = APIRouter(prefix="/api/projects")


@router.post("/{project_id}/context/compile", response_model=ContextCompileOut)
def compile_context_endpoint(
    project_id: str, payload: ContextCompileInput, session: Session = Depends(get_session)
) -> dict:
    return compile_context(
        session,
        project_id,
        focus_node_id=payload.focus_node_id,
        focus_choice_id=payload.focus_choice_id,
        instruction=payload.instruction,
        token_budget=payload.token_budget,
        runtime_state=payload.runtime_state,
    )