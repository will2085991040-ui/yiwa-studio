"""Creative Action + HITL（Step 16）：统一创作动作生命周期。

动作生命周期（User Intent → Proposal → Validation → Confirmation → Execution
→ Artifact/State Commit → Trace）：

- CreativeAction：声明式动作请求（纯数据，不直接改任何状态）。
- risk(): low / medium / high / blocking。
- ActionExecution.execute()：
    * blocking（locked 内容）→ 由 ContentGovernance.assert_editable 抛 409 阻止；
    * high → 进入 ActionProposal（pending），等待确认；
    * low / medium（或已确认）→ 在 CreativeTransaction 内执行并原子提交。
- 统一 ContentGovernance：不按 Agent 各自实现 lock / confirm。
"""
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import ActionProposal, PlayerSession
from app.runtime.state import StateManager
from app.services.governance import ContentGovernance, promote_artifact, revert_artifact
from app.services.transaction import CreativeTransaction

RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_BLOCKING = "low", "medium", "high", "blocking"
SOURCES = ("chat", "button", "node", "choice", "artifact", "storygraph")

# 高风险动作：进入 Proposal/Confirm（治理/破坏性写在列）
_HIGH_OPS = {"promote_artifact", "revert_artifact", "delete_artifact", "abandon_branch"}
# 中风险动作：直接执行但必须走事务（局部生成/状态/写入）
_MEDIUM_OPS = {"write_artifact", "apply_effects", "generate", "revise", "expand", "extend", "branch"}


@dataclass
class CreativeAction:
    operation: str
    source: str = "chat"
    kind: str = ""
    payload: dict = field(default_factory=dict)
    node_id: str | None = None
    choice_id: str | None = None
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id, "source": self.source, "operation": self.operation,
            "kind": self.kind, "payload": self.payload,
            "node_id": self.node_id, "choice_id": self.choice_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CreativeAction":
        return cls(
            operation=data["operation"], source=data.get("source", "chat"), kind=data.get("kind", ""),
            payload=data.get("payload", {}) or {}, node_id=data.get("node_id"), choice_id=data.get("choice_id"),
            action_id=data.get("action_id", str(uuid.uuid4())),
        )

    def risk(self) -> str:
        if self.operation in _HIGH_OPS:
            return RISK_HIGH
        if self.operation in _MEDIUM_OPS:
            return RISK_MEDIUM
        return RISK_LOW


class ActionExecution:
    """统一动作执行器（服务层）。"""

    def __init__(self, session: Session):
        self.session = session

    # -- 提议（HITL）--
    def _propose(self, project_id: str, action: CreativeAction) -> ActionProposal:
        prop = ActionProposal(
            project_id=project_id, source=action.source, operation=action.operation,
            kind=action.kind, payload=action.to_dict(), risk=action.risk(), node_id=action.node_id,
        )
        self.session.add(prop)
        self.session.commit()
        return prop

    def execute(self, project_id: str, action: CreativeAction, *, confirmed: bool = False) -> dict:
        """入口：risk 分级 + 锁定治理 + 执行。"""
        gov = ContentGovernance(self.session, project_id)
        if action.node_id is not None:
            gov.assert_editable(action.node_id)  # locked → 409（blocking）
        if action.risk() == RISK_HIGH and not confirmed:
            prop = self._propose(project_id, action)
            return {"status": "pending", "proposal_id": prop.id}
        return {"status": "executed", **self._run_action(project_id, action)}

    def confirm(self, proposal_id: str, *, approve: bool = True) -> dict:
        prop = self.session.get(ActionProposal, proposal_id)
        if prop is None:
            raise AppError(f"提议 {proposal_id} 不存在", code="proposal_not_found", status=404)
        if prop.status != "pending":
            raise AppError(
                f"提议 {proposal_id} 已处理（当前 {prop.status}）", code="proposal_not_pending", status=409,
            )
        if not approve:
            prop.status = "rejected"
            self.session.commit()
            return {"status": "rejected", "proposal_id": proposal_id}
        action = CreativeAction.from_dict(prop.payload)
        result = self._run_action(prop.project_id, action)
        prop.status = "executed"
        self.session.commit()
        return {"status": "executed", "proposal_id": proposal_id, **result}

    def reject(self, proposal_id: str) -> dict:
        return self.confirm(proposal_id, approve=False)

    # -- 执行分派 --
    def _run_action(self, project_id: str, action: CreativeAction) -> dict:
        op = action.operation
        if op in ("write_artifact", "apply_effects"):
            return self._run_transactional(project_id, action)
        if op == "promote_artifact":
            return {"governance": promote_artifact(
                self.session, project_id=project_id, kind=action.kind, version=action.payload["version"],
            )}
        if op == "revert_artifact":
            return {"governance": revert_artifact(
                self.session, project_id=project_id, kind=action.kind, version=action.payload["version"],
            )}
        raise AppError(f"未知动作操作：{op}", code="invalid_action", status=400)

    def _run_transactional(self, project_id: str, action: CreativeAction) -> dict:
        op = action.operation
        with CreativeTransaction(self.session, project_id=project_id, operation=f"action_{op}") as txn:
            if op == "write_artifact":
                art = txn.stage_artifact(
                    task_id=action.payload.get("task_id", "action"),
                    agent=action.payload.get("agent", "user"),
                    kind=action.kind or action.payload.get("kind", "unknown"),
                    content=action.payload.get("content", {}),
                    prompt_version=action.payload.get("prompt_version", ""),
                    source="user", change_reason=action.payload.get("reason"),
                )
                return {"artifact": {"kind": art.kind, "version": art.version}, "transaction_id": txn.transaction_id}
            # apply_effects
            ps = self.session.get(PlayerSession, action.payload["session_id"])
            if ps is None:
                raise AppError("播放会话不存在", code="session_not_found", status=404)
            sm = StateManager(self.session, ps)
            txn.stage_state(sm, action.payload.get("effects", []))
            return {"state": sm.get_state(), "transaction_id": txn.transaction_id}


def run_action(
    session: Session,
    project_id: str,
    operation: str,
    *,
    source: str = "chat",
    kind: str = "",
    payload: dict | None = None,
    node_id: str | None = None,
    choice_id: str | None = None,
) -> dict:
    action = CreativeAction(
        operation=operation, source=source, kind=kind, payload=payload or {},
        node_id=node_id, choice_id=choice_id,
    )
    return ActionExecution(session).execute(project_id, action)


def validate_action_payload(operation: str, payload: dict) -> Callable[[], None]:
    """返回一个校验函数（供 CreativeTransaction.validate 使用）：校验动作 payload 完整性。"""
    def _check() -> None:
        if operation == "promote_artifact" or operation == "revert_artifact":
            if not payload.get("version"):
                raise AppError(f"{operation} 缺少 version", code="invalid_action", status=400)
        if operation == "apply_effects":
            if not payload.get("session_id") or payload.get("effects") is None:
                raise AppError("apply_effects 缺少 session_id/effects", code="invalid_action", status=400)
        if operation == "write_artifact":
            if payload.get("content") is None:
                raise AppError("write_artifact 缺少 content", code="invalid_action", status=400)
    return _check