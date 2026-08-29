"""Trace 管理器：每次运行/步骤全量落库（轨迹回放的数据基础）。"""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AgentRun, AgentStep


class TraceManager:
    """在业务服务中注入使用；所有写库操作与业务同事务。"""

    def start_run(
        self,
        session: Session,
        *,
        kind: str,
        agent_version_id: str | None = None,
        meta: dict | None = None,
    ) -> AgentRun:
        run = AgentRun(kind=kind, agent_version_id=agent_version_id, meta=meta or {}, status="running")
        session.add(run)
        session.flush()
        return run

    def add_step(
        self,
        session: Session,
        run: AgentRun,
        *,
        agent: str,
        step_key: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        latency_ms: int = 0,
        token_usage: dict | None = None,
        error: str | None = None,
        status: str = "ok",
    ) -> AgentStep:
        seq = len(run.steps) + 1
        step = AgentStep(
            agent_run_id=run.id, seq=seq, agent=agent, step_key=step_key,
            input_data=input_data, output_data=output_data, latency_ms=latency_ms,
            token_usage=token_usage or {}, error=error, status=status,
        )
        session.add(step)
        session.flush()
        return step

    def finish_run(self, run: AgentRun, *, status: str = "ok") -> None:
        run.status = status
        run.finished_at = datetime.now(UTC)


trace_manager = TraceManager()
