"""API：Interactive Runtime（Step 13）—— 创建会话 / 获取会话 / 可见选项 / 执行选择。

最小闭环：创建会话 → 当前节点 → 获取可见 Choices → 执行 Choice → 条件求值 → 效果应用
→ StateManager commit → next_node → 返回新状态。
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.base import get_session
from app.runtime.session_service import (
    choose_choice,
    create_runtime_session,
    get_runtime_session,
    runtime_choices,
)
from app.schemas import ChoiceInput, RuntimeChoiceOut, RuntimeSessionOut

router = APIRouter(prefix="/api/projects")


@router.post("/{project_id}/runtime/sessions", response_model=RuntimeSessionOut)
def create_session(project_id: str, session: Session = Depends(get_session)) -> dict:
    return create_runtime_session(session, project_id)


@router.get("/{project_id}/runtime/sessions/{session_id}", response_model=RuntimeSessionOut)
def read_session(project_id: str, session_id: str, session: Session = Depends(get_session)) -> dict:
    return get_runtime_session(session, project_id, session_id)


@router.get("/{project_id}/runtime/sessions/{session_id}/choices", response_model=list[RuntimeChoiceOut])
def list_choices(project_id: str, session_id: str, session: Session = Depends(get_session)) -> list[dict]:
    return runtime_choices(session, project_id, session_id)


@router.post("/{project_id}/runtime/sessions/{session_id}/choice", response_model=RuntimeSessionOut)
def make_choice(
    project_id: str, session_id: str, payload: ChoiceInput, session: Session = Depends(get_session)
) -> dict:
    return choose_choice(session, project_id, session_id, payload.choice_id)