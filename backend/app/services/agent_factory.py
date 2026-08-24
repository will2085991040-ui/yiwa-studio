"""Agent Factory：Golden Path 第一阶段（自然语言目标 → Project + AgentSpec + AgentVersion）。

真实执行：一个事务内完成 Project/AgentSpec(v1 计划)/AgentVersion v1 的创建，
并记录完整 Trace（AgentRun + AgentStep）。不使用任何固定 JSON 冒充 Agent——
计划步骤与模板由 planner 按目标真实推导，状态如实为 pending。
"""
import time

from sqlalchemy.orm import Session

from app.models import AgentSpec, AgentVersion, Project
from app.services.planner import build_plan
from app.trace.manager import trace_manager


def _make_title(goal: str) -> str:
    cleaned = " ".join(goal.split())
    return cleaned[:60] + ("…" if len(cleaned) > 60 else "")


def create_agent_from_goal(session: Session, goal: str) -> dict:
    started = time.perf_counter()

    plan = build_plan(goal)
    project = Project(
        goal=goal,
        template=plan.template,
        title=_make_title(goal),
        status="draft",
    )
    session.add(project)
    session.flush()

    spec = AgentSpec(
        project_id=project.id,
        goal_summary=plan.goal_summary,
        plan=plan.steps,
        policies={
            "budget": {"project_total_usd": None, "agent_limits": {}},
            "safety": {"forbidden_topics": [], "require_approval_for_optimization": True},
        },
        status="draft",
    )
    session.add(spec)
    session.flush()

    version = AgentVersion(
        agent_spec_id=spec.id,
        version_no=1,
        label="v1 · 初始骨架",
        spec_snapshot={
            "goal": goal,
            "template": plan.template,
            "goal_summary": plan.goal_summary,
            "plan": plan.steps,
            "policies": spec.policies,
        },
        status="draft",
    )
    session.add(version)
    session.flush()

    run = trace_manager.start_run(session, kind="create_agent", agent_version_id=version.id, meta={"goal": goal})
    trace_manager.add_step(
        session,
        run,
        agent="planner",
        step_key="understand_goal",
        input_data={"goal": goal},
        output_data={"template": plan.template, "goal_summary": plan.goal_summary},
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    trace_manager.finish_run(run, status="ok")
    session.commit()

    return {
        "project_id": project.id,
        "goal": goal,
        "template": plan.template,
        "agent_spec": {
            "id": spec.id,
            "goal_summary": spec.goal_summary,
            "template": plan.template,
            "status": spec.status,
            "plan": plan.steps,
        },
        "agent_version": {
            "id": version.id,
            "version_no": version.version_no,
            "label": version.label,
            "status": version.status,
            "created_at": version.created_at,
        },
    }
