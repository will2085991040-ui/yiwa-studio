"""Creative Transaction（Step 14）：一次创作操作的原子闭环。

「生成 → 校验 → 提交」的最小落地：优先复用 SQLAlchemy 事务 + Artifact 版本链 + Trace +
StateManager，不制造复杂事务框架。

核心原则：Artifact 写入 / Runtime State 提交 / Trace 写入 全部放进同一个 DB 事务，
任一环节失败 → 整体回滚，不留半成品、不产生「成功完成」的 Trace。

用法（context manager）：
    with CreativeTransaction(session, project_id=pid, operation="dialogue_generate") as txn:
        txn.validate([("schema", lambda: _ensure_schema(content))])
        txn.stage_artifact(kind=..., task_id=..., agent=..., content=content, prompt_version=...)
        txn.stage_state(sm, effects)
        txn.add_trace_step(agent="dialogue", step_key="artifact", input_data=..., output_data=...)
    # 正常退出 → commit()；中间抛异常 → rollback()
"""
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Artifact
from app.runtime.state import StateManager
from app.services.artifacts import persist_versioned_artifact
from app.trace.manager import trace_manager


class CreativeTransaction:
    def __init__(self, session: Session, *, project_id: str, operation: str):
        self.session = session
        self.project_id = project_id
        self.operation = operation
        self.transaction_id = str(uuid.uuid4())
        self._run = None
        self._artifact_changes: list[dict] = []
        self._state_changes: list[dict] = []
        self._closed = False

    # -- begin --
    def begin(self) -> "CreativeTransaction":
        self._run = trace_manager.start_run(
            self.session,
            kind=f"txn_{self.operation}",
            meta={
                "transaction_id": self.transaction_id,
                "project_id": self.project_id,
                "operation": self.operation,
            },
        )
        return self

    def __enter__(self) -> "CreativeTransaction":
        return self.begin()

    # -- validate --
    def validate(self, checks: list[tuple[str, Callable[[], None]]]) -> None:
        """顺序执行一组同步校验；首个失败即抛出，触发事务回滚。"""
        for label, check in checks:
            try:
                check()
            except AppError:
                raise
            except Exception as exc:
                raise AppError(f"校验失败：{label}", code="validation_failed", status=422) from exc

    # -- stage：把 Artifact / Runtime State 变更纳入同一事务 --
    def stage_artifact(
        self,
        *,
        task_id: str,
        agent: str,
        kind: str,
        content: dict,
        prompt_version: str,
        source: str = "agent",
        change_reason: str | None = None,
    ) -> Artifact:
        artifact = persist_versioned_artifact(
            self.session,
            project_id=self.project_id,
            task_id=task_id,
            agent=agent,
            kind=kind,
            content=content,
            prompt_version=prompt_version,
            source=source,
            change_reason=change_reason,
        )
        self._artifact_changes.append({"kind": kind, "version": artifact.version})
        return artifact

    def stage_state(self, manager: StateManager, effects: list[dict]) -> dict:
        previous = manager.get_state()
        new_state = manager.apply_effects(effects)   # 非法效果在此抛出 → 回滚
        manager.commit()                              # 写回 PlayerSession（未最终 DB commit）
        self._state_changes.append({"previous": previous, "effects": effects, "state": new_state})
        return new_state

    def add_trace_step(
        self, *, agent: str, step_key: str, input_data: dict, output_data: dict, status: str = "ok",
    ) -> None:
        trace_manager.add_step(
            self.session, self._run, agent=agent, step_key=step_key,
            input_data=input_data, output_data=output_data, status=status,
        )

    # -- commit / rollback --
    def commit(self) -> None:
        if self._closed:
            return
        self._closed = True
        trace_manager.add_step(
            self.session, self._run, agent="transaction", step_key="txn.summary",
            input_data={"operation": self.operation, "project_id": self.project_id},
            output_data={
                "transaction_id": self.transaction_id,
                "artifact_changes": self._artifact_changes,
                "runtime_state_changes": self._state_changes,
            },
        )
        trace_manager.finish_run(self._run, status="ok")
        self.session.commit()

    def rollback(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.session.rollback()  # 丢弃 Artifact / Runtime State / Trace 的水半成品
        # 在干净事务里记录一条「回滚」Trace；绝不伪装成成功
        try:
            run = trace_manager.start_run(
                self.session,
                kind=f"txn_{self.operation}",
                meta={
                    "transaction_id": self.transaction_id,
                    "project_id": self.project_id,
                    "operation": self.operation,
                    "rollback": True,
                },
            )
            trace_manager.add_step(
                self.session, run, agent="transaction", step_key="rollback",
                input_data={"operation": self.operation, "project_id": self.project_id},
                output_data={"rollback": True, "transaction_id": self.transaction_id},
            )
            trace_manager.finish_run(run, status="failed")
            self.session.commit()
        except Exception:
            self.session.rollback()

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False